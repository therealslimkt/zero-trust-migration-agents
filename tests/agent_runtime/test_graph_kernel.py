from __future__ import annotations

import asyncio

import pytest

from agent_runtime.graph import (
    CatalogGraphKernel,
    CatalogProbe,
    CatalogProbeKind,
    CatalogRoute,
    GraphConflictError,
    GraphPhase,
    GraphStatus,
    InterruptKind,
    ResumeInput,
)
from agent_runtime.graph.kernel import CatalogCallbacks


class Store:
    def __init__(self):
        self.value = None

    async def load(self, *, tenant_id, run_id):
        if self.value is None:
            return None
        assert (self.value.tenant_id, self.value.run_id) == (tenant_id, run_id)
        return self.value

    async def compare_and_set(self, *, expected_revision, snapshot):
        actual = None if self.value is None else self.value.revision
        if actual != expected_revision:
            raise GraphConflictError("revision_conflict")
        self.value = snapshot
        return snapshot


class Effects:
    def __init__(self):
        self.operations = set()
        self.active = 0
        self.peak = 0

    async def validate(self, operation_id):
        self.operations.add(operation_id)

    def probe(self, kind, **facts):
        async def execute(operation_id):
            self.operations.add(operation_id)
            self.active += 1
            self.peak = max(self.peak, self.active)
            # A short yield proves overlap when all three graph branches start,
            # while still allowing a partially persisted fan-out to resume.
            await asyncio.sleep(0.01)
            self.active -= 1
            return CatalogProbe(kind=kind, **facts)

        return execute

    def callbacks(self, **facts):
        return CatalogCallbacks(
            validate_intent=self.validate,
            metadata=self.probe(CatalogProbeKind.METADATA, **facts),
            vector=self.probe(CatalogProbeKind.VECTOR, **facts),
            access=self.probe(CatalogProbeKind.ACCESS, **facts),
        )


def run(coro):
    return asyncio.run(coro)


def test_catalog_probes_are_concurrent_then_joined_in_stable_graph_order():
    store = Store()
    effects = Effects()
    state = run(
        CatalogGraphKernel(store=store, callbacks=effects.callbacks()).run(
            tenant_id="tenant_AAA", run_id="run_CATALOG0001"
        )
    )
    assert effects.peak == 3
    assert state.catalog_route is CatalogRoute.MIGRATE
    assert state.phase is GraphPhase.ROUTED
    assert state.status is GraphStatus.SUCCEEDED
    assert state.model_calls == 0
    assert state.checkpoint.sequence == 8
    assert state.checkpoint.model_calls == 0
    assert state.checkpoint.resumable is True
    assert [probe.kind for probe in state.probes] == list(CatalogProbeKind)
    event_types = [event.event_type for event in state.events]
    assert event_types == [
        "run_started",
        "node_succeeded",
        "node_succeeded",
        "node_succeeded",
        "node_succeeded",
        "fanout_completed",
        "join_completed",
        "route_selected",
    ]
    assert [event.sequence for event in state.events] == list(range(1, 9))


@pytest.mark.parametrize("kill_after_sequence", range(1, 9))
def test_kill_after_every_commit_fast_forwards_without_duplicate_effects(kill_after_sequence):
    store = Store()
    effects = Effects()
    killed = False

    async def kill_once(state):
        nonlocal killed
        if state.events[-1].sequence == kill_after_sequence and not killed:
            killed = True
            raise RuntimeError("simulated_process_death")

    first = CatalogGraphKernel(
        store=store, callbacks=effects.callbacks(), after_commit=kill_once
    )
    with pytest.raises(RuntimeError, match="simulated_process_death"):
        run(first.run(tenant_id="tenant_AAA", run_id="run_CATALOG0001"))

    # New callbacks model a restarted process. Operation IDs remain stable and
    # are the adapter-level idempotency keys for work attempted before a crash.
    restarted_effects = Effects()
    final = run(
        CatalogGraphKernel(
            store=store, callbacks=restarted_effects.callbacks()
        ).run(tenant_id="tenant_AAA", run_id="run_CATALOG0001")
    )
    assert final.phase is GraphPhase.ROUTED
    assert len(final.events) == 8
    assert len({event.operation_id for event in final.events if event.node_id.startswith("catalog_")}) == 5
    assert final.model_calls == 0


def test_unique_interrupts_and_idempotent_clarification_resume():
    store = Store()
    effects = Effects()
    kernel = CatalogGraphKernel(store=store, callbacks=effects.callbacks())
    run(kernel.run(tenant_id="tenant_AAA", run_id="run_CATALOG0001"))

    clarification = run(
        kernel.request_interrupt(
            tenant_id="tenant_AAA",
            run_id="run_CATALOG0001",
            kind=InterruptKind.CLARIFICATION,
        )
    )
    pending = clarification.pending_interrupt
    assert pending is not None
    assert pending.resume_channel == "input_endpoint"
    value = ResumeInput(
        interrupt_id=pending.interrupt_id,
        checkpoint_id=pending.checkpoint_id,
        idempotency_key="resume-key-0001",
        text="JDE EnterpriseOne",
    )
    resumed = run(
        kernel.resume(
            tenant_id="tenant_AAA", run_id="run_CATALOG0001", value=value
        )
    )
    repeated = run(
        kernel.resume(
            tenant_id="tenant_AAA", run_id="run_CATALOG0001", value=value
        )
    )
    assert repeated == resumed
    assert repeated.pending_interrupt is None
    assert repeated.events[-1].event_type == "interrupt_resumed"
    with pytest.raises(GraphConflictError, match="idempotency_key_reused"):
        run(
            kernel.resume(
                tenant_id="tenant_AAA",
                run_id="run_CATALOG0001",
                value=ResumeInput(
                    interrupt_id=value.interrupt_id,
                    checkpoint_id=value.checkpoint_id,
                    idempotency_key=value.idempotency_key,
                    text="different answer",
                ),
            )
        )

    simulation = run(
        kernel.request_interrupt(
            tenant_id="tenant_AAA",
            run_id="run_CATALOG0001",
            kind=InterruptKind.SIMULATION_APPROVAL,
            subject_digest="sha256:" + "a" * 64,
        )
    )
    assert simulation.pending_interrupt.interrupt_id != pending.interrupt_id
    assert simulation.pending_interrupt.resume_channel == "approval_endpoint"
    forged = ResumeInput(
        interrupt_id=simulation.pending_interrupt.interrupt_id,
        checkpoint_id=simulation.pending_interrupt.checkpoint_id,
        idempotency_key="resume-key-0002",
        text="approved",
    )
    with pytest.raises(GraphConflictError, match="approval_not_resumable_via_input"):
        run(
            kernel.resume(
                tenant_id="tenant_AAA", run_id="run_CATALOG0001", value=forged
            )
        )


def test_interrupt_ids_are_unique_across_kinds_and_three_repair_cycles():
    generated = {
        CatalogGraphKernel._interrupt_id("run_CATALOG0001", kind, ordinal)
        for kind in InterruptKind
        for ordinal in range(1, 4)
    }
    assert len(generated) == 9
    assert all(value.startswith("int_") for value in generated)


def test_mismatched_resume_makes_no_state_change():
    store = Store()
    effects = Effects()
    kernel = CatalogGraphKernel(store=store, callbacks=effects.callbacks())
    run(kernel.run(tenant_id="tenant_AAA", run_id="run_CATALOG0001"))
    paused = run(
        kernel.request_interrupt(
            tenant_id="tenant_AAA",
            run_id="run_CATALOG0001",
            kind=InterruptKind.CLARIFICATION,
        )
    )
    before = store.value
    with pytest.raises(GraphConflictError, match="checkpoint_mismatch"):
        run(
            kernel.resume(
                tenant_id="tenant_AAA",
                run_id="run_CATALOG0001",
                value=ResumeInput(
                    interrupt_id=paused.pending_interrupt.interrupt_id,
                    checkpoint_id="ckpt_wrong00000000",
                    idempotency_key="resume-key-0003",
                    text="answer",
                ),
            )
        )
    assert store.value == before
