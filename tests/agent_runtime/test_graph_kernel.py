from __future__ import annotations

import asyncio
import dataclasses

import pytest

from agent_runtime.graph import (
    CatalogGraphKernel,
    CatalogProbe,
    CatalogProbeKind,
    CatalogRoute,
    GraphConflictError,
    GraphEvent,
    GraphInvariantError,
    GraphPhase,
    GraphSnapshot,
    GraphStatus,
    InterruptKind,
    PlanRouteInput,
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


def stop_after_validation(store, effects):
    async def stop(state):
        if state.phase is GraphPhase.VALIDATED:
            raise RuntimeError("stop_at_resumable_checkpoint")

    with pytest.raises(RuntimeError, match="stop_at_resumable_checkpoint"):
        run(
            CatalogGraphKernel(
                store=store, callbacks=effects.callbacks(), after_commit=stop
            ).run(tenant_id="tenant_AAA", run_id="run_CATALOG0001")
        )
    assert store.value.phase is GraphPhase.VALIDATED
    return CatalogGraphKernel(store=store, callbacks=effects.callbacks())


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
    assert state.checkpoint.resumable is False
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


def test_probe_failure_cancels_and_awaits_all_siblings_before_returning():
    store = Store()
    started = 0
    all_started = asyncio.Event()
    task_refs = []
    post_failure_effects = []

    async def validate(operation_id):
        return None

    async def enter_probe():
        nonlocal started
        task_refs.append(asyncio.current_task())
        started += 1
        if started == 3:
            all_started.set()
        await all_started.wait()

    async def fail(operation_id):
        await enter_probe()
        raise RuntimeError("metadata_probe_failed")

    def sibling(kind):
        async def wait_for_cancellation(operation_id):
            await enter_probe()
            await asyncio.sleep(60)
            post_failure_effects.append(kind.value)
            return CatalogProbe(kind=kind)

        return wait_for_cancellation

    callbacks = CatalogCallbacks(
        validate_intent=validate,
        metadata=fail,
        vector=sibling(CatalogProbeKind.VECTOR),
        access=sibling(CatalogProbeKind.ACCESS),
    )

    async def exercise():
        with pytest.raises(RuntimeError, match="metadata_probe_failed"):
            await CatalogGraphKernel(store=store, callbacks=callbacks).run(
                tenant_id="tenant_AAA", run_id="run_PROBEFAIL001"
            )
        # If cancellation were fire-and-forget, this yield would expose either
        # a still-pending task or a late mutation after the kernel returned.
        await asyncio.sleep(0)
        assert len(task_refs) == 3
        assert all(task.done() for task in task_refs)
        assert all(
            task.cancelled() for task in task_refs if task.get_name() != "catalog_metadata"
        )
        assert post_failure_effects == []

    run(exercise())


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
    assert len({event.operation_id for event in final.events}) == len(final.events)
    assert final.model_calls == 0


def test_unique_interrupts_and_idempotent_clarification_resume():
    store = Store()
    effects = Effects()
    kernel = stop_after_validation(store, effects)

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
    assert repeated.phase is GraphPhase.VALIDATED
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
    kernel = stop_after_validation(store, effects)
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


def test_resume_restores_exact_phase_then_skips_completed_work():
    store = Store()
    effects = Effects()
    kernel = stop_after_validation(store, effects)
    paused = run(
        kernel.request_interrupt(
            tenant_id="tenant_AAA",
            run_id="run_CATALOG0001",
            kind=InterruptKind.CLARIFICATION,
        )
    )
    assert paused.paused_from_phase is GraphPhase.VALIDATED
    assert paused.phase is GraphPhase.PAUSED
    value = ResumeInput(
        interrupt_id=paused.pending_interrupt.interrupt_id,
        checkpoint_id=paused.pending_interrupt.checkpoint_id,
        idempotency_key="resume-key-restore",
        text="complete intent",
    )
    resumed = run(
        kernel.resume(
            tenant_id="tenant_AAA", run_id="run_CATALOG0001", value=value
        )
    )
    assert resumed.phase is GraphPhase.VALIDATED
    assert resumed.pending_interrupt is None
    final = run(kernel.run(tenant_id="tenant_AAA", run_id="run_CATALOG0001"))
    assert final.phase is GraphPhase.ROUTED
    assert [event.node_id for event in final.events].count("validate_intent") == 1
    assert len({event.operation_id for event in final.events}) == len(final.events)
    assert [event.sequence for event in final.events] == list(
        range(1, len(final.events) + 1)
    )


def test_needs_input_routes_to_a_real_awaiting_input_pause():
    store = Store()
    effects = Effects()
    state = run(
        CatalogGraphKernel(
            store=store,
            callbacks=effects.callbacks(missing_input=True),
        ).run(tenant_id="tenant_AAA", run_id="run_NEEDSINPUT01")
    )
    assert state.catalog_route is CatalogRoute.NEEDS_INPUT
    assert state.phase is GraphPhase.PAUSED
    assert state.status is GraphStatus.AWAITING_INPUT
    assert state.paused_from_phase is GraphPhase.JOINED
    assert state.pending_interrupt.kind is InterruptKind.CLARIFICATION
    assert state.events[-2].detail["selected_edge"] == "NEEDS_INPUT"
    assert state.events[-1].event_type == "interrupt_requested"


def test_needs_input_route_and_pause_commit_atomically_across_crash():
    store = Store()
    effects = Effects()

    async def die_after_pause(state):
        if state.phase is GraphPhase.PAUSED:
            raise RuntimeError("crash_after_atomic_pause")

    kernel = CatalogGraphKernel(
        store=store,
        callbacks=effects.callbacks(missing_input=True),
        after_commit=die_after_pause,
    )
    with pytest.raises(RuntimeError, match="crash_after_atomic_pause"):
        run(kernel.run(tenant_id="tenant_AAA", run_id="run_ATOMICPAUSE1"))
    before = store.value
    restarted = CatalogGraphKernel(
        store=store, callbacks=Effects().callbacks(missing_input=True)
    )
    after = run(
        restarted.run(tenant_id="tenant_AAA", run_id="run_ATOMICPAUSE1")
    )
    assert after == before
    assert [event.event_type for event in after.events].count("route_selected") == 1
    assert [event.event_type for event in after.events].count("interrupt_requested") == 1
    assert len({event.operation_id for event in after.events}) == len(after.events)


def test_corrupted_checkpoint_binding_cannot_resume():
    store = Store()
    kernel = stop_after_validation(store, Effects())
    paused = run(
        kernel.request_interrupt(
            tenant_id="tenant_AAA",
            run_id="run_CATALOG0001",
            kind=InterruptKind.CLARIFICATION,
        )
    )
    forged_interrupt = dataclasses.replace(
        paused.pending_interrupt, checkpoint_id="ckpt_" + "f" * 32
    )
    store.value = dataclasses.replace(paused, pending_interrupt=forged_interrupt)
    with pytest.raises(GraphConflictError, match="checkpoint_not_resumable"):
        run(
            kernel.resume(
                tenant_id="tenant_AAA",
                run_id="run_CATALOG0001",
                value=ResumeInput(
                    interrupt_id=forged_interrupt.interrupt_id,
                    checkpoint_id=forged_interrupt.checkpoint_id,
                    idempotency_key="forged-checkpoint-key",
                    text="answer",
                ),
            )
        )


@pytest.mark.parametrize(
    ("phase", "status"),
    [
        (GraphPhase.ROUTED, GraphStatus.RUNNING),
        (GraphPhase.ROUTED, GraphStatus.SUCCEEDED),
        (GraphPhase.VALIDATED, GraphStatus.SUCCEEDED),
        (GraphPhase.VALIDATED, GraphStatus.FAILED),
        (GraphPhase.COMPLETE, GraphStatus.SUCCEEDED),
        (GraphPhase.FAILED, GraphStatus.FAILED),
    ],
)
def test_terminal_states_cannot_be_interrupted_or_resurrected(phase, status):
    store = Store()
    store.value = GraphSnapshot(
        tenant_id="tenant_AAA",
        run_id="run_TERMINAL001",
        phase=phase,
        status=status,
    )
    kernel = CatalogGraphKernel(store=store, callbacks=Effects().callbacks())
    with pytest.raises(GraphConflictError, match="terminal_run"):
        run(
            kernel.request_interrupt(
                tenant_id="tenant_AAA",
                run_id="run_TERMINAL001",
                kind=InterruptKind.CLARIFICATION,
            )
        )
    with pytest.raises(GraphConflictError, match="terminal_run"):
        run(
            kernel.resume(
                tenant_id="tenant_AAA",
                run_id="run_TERMINAL001",
                value=ResumeInput(
                    interrupt_id="int_terminal000001",
                    checkpoint_id=store.value.checkpoint_id,
                    idempotency_key="terminal-resume-key",
                    text="resurrect",
                ),
            )
        )
    assert store.value.revision == 0


def test_plan_route_persists_three_repairs_then_fails_closed():
    store = Store()
    store.value = GraphSnapshot(
        tenant_id="tenant_AAA",
        run_id="run_REPAIRS0001",
        phase=GraphPhase.PLANNING,
    )
    kernel = CatalogGraphKernel(store=store, callbacks=Effects().callbacks())
    for expected in (1, 2, 3):
        state = run(
            kernel.apply_plan_route(
                tenant_id="tenant_AAA",
                run_id="run_REPAIRS0001",
                value=PlanRouteInput(needs_research=True),
            )
        )
        assert state.repair_count == expected
        assert state.status is GraphStatus.RUNNING
    failed = run(
        kernel.apply_plan_route(
            tenant_id="tenant_AAA",
            run_id="run_REPAIRS0001",
            value=PlanRouteInput(needs_research=True),
        )
    )
    assert failed.repair_count == 3
    assert failed.phase is GraphPhase.FAILED
    assert failed.status is GraphStatus.FAILED
    assert failed.events[-1].detail["selected_edge"] == "REJECTED"
    with pytest.raises(GraphConflictError, match="terminal_run"):
        run(
            kernel.apply_plan_route(
                tenant_id="tenant_AAA",
                run_id="run_REPAIRS0001",
                value=PlanRouteInput(ready=True),
            )
        )


def test_plan_needs_input_pauses_and_resumes_the_planning_phase():
    store = Store()
    store.value = GraphSnapshot(
        tenant_id="tenant_AAA",
        run_id="run_PLANINPUT001",
        phase=GraphPhase.PLANNING,
    )
    kernel = CatalogGraphKernel(store=store, callbacks=Effects().callbacks())
    paused = run(
        kernel.apply_plan_route(
            tenant_id="tenant_AAA",
            run_id="run_PLANINPUT001",
            value=PlanRouteInput(needs_input=True),
        )
    )
    assert paused.phase is GraphPhase.PAUSED
    assert paused.paused_from_phase is GraphPhase.PLANNING
    resumed = run(
        kernel.resume(
            tenant_id="tenant_AAA",
            run_id="run_PLANINPUT001",
            value=ResumeInput(
                interrupt_id=paused.pending_interrupt.interrupt_id,
                checkpoint_id=paused.pending_interrupt.checkpoint_id,
                idempotency_key="plan-input-resume",
                text="planning answer",
            ),
        )
    )
    assert resumed.phase is GraphPhase.PLANNING
    assert resumed.status is GraphStatus.RUNNING


def test_plan_route_rejects_non_planning_snapshots():
    store = Store()
    store.value = GraphSnapshot(
        tenant_id="tenant_AAA", run_id="run_NOTPLANNING1"
    )
    kernel = CatalogGraphKernel(store=store, callbacks=Effects().callbacks())
    with pytest.raises(GraphConflictError, match="plan_phase"):
        run(
            kernel.apply_plan_route(
                tenant_id="tenant_AAA",
                run_id="run_NOTPLANNING1",
                value=PlanRouteInput(ready=True),
            )
        )


def test_checkpoint_ids_bind_full_run_tenant_and_unbounded_revision():
    left = GraphSnapshot(
        tenant_id="tenant_AAA",
        run_id="run_LEFTsame_suffix",
        revision=10**30,
    )
    right = GraphSnapshot(
        tenant_id="tenant_AAA",
        run_id="run_RIGHTsame_suffix",
        revision=10**30,
    )
    other_tenant = GraphSnapshot(
        tenant_id="tenant_BBB",
        run_id=left.run_id,
        revision=left.revision,
    )
    assert len({left.checkpoint_id, right.checkpoint_id, other_tenant.checkpoint_id}) == 3
    assert all(
        value.startswith("ckpt_") and len(value) == 37
        for value in (
            left.checkpoint_id,
            right.checkpoint_id,
            other_tenant.checkpoint_id,
        )
    )


def test_model_call_accounting_records_each_observed_invocation_once():
    store = Store()
    store.value = GraphSnapshot(
        tenant_id="tenant_AAA", run_id="run_MODELCALL001"
    )
    kernel = CatalogGraphKernel(store=store, callbacks=Effects().callbacks())
    first = run(
        kernel.record_model_call(
            tenant_id="tenant_AAA",
            run_id="run_MODELCALL001",
            agent_id="scout",
            invocation_id="inv_MODELBOUNDARY001",
        )
    )
    repeated = run(
        kernel.record_model_call(
            tenant_id="tenant_AAA",
            run_id="run_MODELCALL001",
            agent_id="scout",
            invocation_id="inv_MODELBOUNDARY001",
        )
    )
    second = run(
        kernel.record_model_call(
            tenant_id="tenant_AAA",
            run_id="run_MODELCALL001",
            agent_id="prisma",
            invocation_id="inv_MODELBOUNDARY002",
        )
    )
    assert repeated == first
    assert second.model_calls == 2
    assert [event.model_calls for event in second.events] == [1, 1]
    before = store.value
    with pytest.raises(GraphInvariantError, match="model_agent_id"):
        run(
            kernel.record_model_call(
                tenant_id="tenant_AAA",
                run_id="run_MODELCALL001",
                agent_id="catalog_metadata",
                invocation_id="inv_FAKEBOUNDARY0001",
            )
        )
    assert store.value == before


def test_event_model_call_counts_are_closed_to_observed_call_events():
    with pytest.raises(GraphInvariantError, match="event_model_call_type"):
        GraphEvent(
            sequence=1,
            event_type="node_succeeded",
            node_id="catalog_metadata",
            operation_id="op_deterministic0001",
            model_calls=1,
        )
    with pytest.raises(GraphInvariantError, match="event_model_call_count"):
        GraphEvent(
            sequence=1,
            event_type="model_call_observed",
            node_id="scout",
            operation_id="inv_MODELBOUNDARY003",
            model_calls=0,
        )
