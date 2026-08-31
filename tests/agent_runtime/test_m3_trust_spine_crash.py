"""Crash and resume tests for the Milestone 3 trust spine.

A crash is modelled as :class:`Crash`, a ``BaseException`` that node-level
error handling deliberately does not catch, so the process "dies" without
journalling a failure. Resume is modelled the only way the runtime supports
it: calling ``execute`` again with the same frozen plan.

The properties under test are:

* a crash before an effect, after an effect but before its success is
  persisted, and after each node all resume to the same certified result;
* every port sees at most one real effect per idempotency key;
* a replay that produces a *different* answer fails closed.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent_runtime.trust_spine import (
    NODE_PLAN,
    ApprovalRecord,
    BudgetError,
    BudgetPolicy,
    CanonicalMap,
    Certificate,
    DispatchReceipt,
    DispatchRequest,
    DurabilityError,
    FailureCode,
    FlowKernel,
    ForgeKernel,
    FrozenPlan,
    LedgerKernel,
    NodeName,
    NodeStatus,
    ParameterSpec,
    PolicyConfig,
    PolicyKernel,
    PrismaKernel,
    ReconciliationReport,
    RegistryError,
    RegistryTemplate,
    RunCheckpoint,
    RunPhase,
    RunRequest,
    Stage,
    TrustSpineRuntime,
    ValeKernel,
    ValueKind,
    derive_approval_key,
    digest_of,
    digest_of_text,
    expected_effect_digest,
)
from agent_runtime.trust_spine import Decision

TENANT = "acme_corp"
RUN_ID = "run_20260830_000042"
SOURCE = digest_of_text("source://milestone3/crash")


class Crash(BaseException):
    """Simulated process death: never caught by node-level error handling."""


class FakeStore:
    """Durable store whose writes can be interrupted at a chosen event.

    ``_tick`` fires *before* the write lands, so a crash means the write did
    not happen -- the harshest interpretation of a partial failure.
    """

    def __init__(self) -> None:
        self.node_records: dict[tuple[str, str], list] = {}
        self.approval_records: dict[tuple[str, str], list] = {}
        self.checkpoints: dict[tuple[str, str], RunCheckpoint] = {}
        self.results: dict[tuple[str, str], object] = {}
        self.counts: dict[str, int] = {}
        self.crash_event: str | None = None
        self.crash_at: int = 0

    def _tick(self, event: str) -> None:
        count = self.counts.get(event, 0) + 1
        self.counts[event] = count
        if self.crash_event == event and count == self.crash_at:
            raise Crash(f"{event}#{count}")

    def append_node_record(self, record) -> None:
        self._tick("append_node_record")
        self.node_records.setdefault((record.tenant_id, record.run_id), []).append(record)

    def load_node_records(self, tenant_id: str, run_id: str) -> tuple:
        return tuple(self.node_records.get((tenant_id, run_id), ()))

    def append_approval(self, record) -> None:
        self._tick("append_approval")
        self.approval_records.setdefault((record.tenant_id, record.run_id), []).append(record)

    def commit_production_approval(self, expected_checkpoint, record, sealed_checkpoint) -> None:
        self._tick("commit_production_approval")
        key = (record.tenant_id, record.run_id)
        if self.checkpoints.get(key) != expected_checkpoint:
            raise DurabilityError(FailureCode.RUN_CONFLICT, "checkpoint CAS conflict")
        self.approval_records.setdefault(key, []).append(record)
        self.checkpoints[key] = sealed_checkpoint

    def load_approvals(self, tenant_id: str, run_id: str) -> tuple:
        return tuple(self.approval_records.get((tenant_id, run_id), ()))

    def write_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        self._tick("write_checkpoint")
        self.checkpoints[(checkpoint.tenant_id, checkpoint.run_id)] = checkpoint

    def load_checkpoint(self, tenant_id: str, run_id: str):
        return self.checkpoints.get((tenant_id, run_id))

    def store_result(self, result) -> None:
        self._tick("store_result")
        self.results[(result.tenant_id, result.run_id)] = result

    def load_result(self, tenant_id: str, run_id: str):
        return self.results.get((tenant_id, run_id))


class FakeRepairAdapter:
    def __init__(self, responses: dict[int, CanonicalMap] | None = None) -> None:
        self.adapter_id = "prisma.repair.adapter"
        self.responses = dict(responses or {})
        self.calls: list[str] = []
        self.crash_after_calls: set[int] = set()

    def repair(self, request) -> CanonicalMap:
        self.calls.append(request.idempotency_key)
        if request.attempt not in self.responses:
            raise LookupError("no repair candidate for this attempt")
        response = self.responses[request.attempt]
        if len(self.calls) in self.crash_after_calls:
            raise Crash("repair adapter crashed after its boundary entry")
        return response


class FakeDispatcher:
    def __init__(self, template: RegistryTemplate, dispatcher_id: str = "flow.dispatcher") -> None:
        self.dispatcher_id = dispatcher_id
        self.template = template
        self.effects: dict[str, DispatchReceipt] = {}
        self.effect_keys: list[str] = []
        self.replays = 0
        self.dispatch_salt = ""
        self.crash_before_effect = False
        self.crash_after_effect = False

    def resolve_template(self, template_id: str, template_version: str) -> RegistryTemplate:
        if (template_id, template_version) != (
            self.template.template_id,
            self.template.template_version,
        ):
            raise RegistryError(FailureCode.TEMPLATE_NOT_REGISTERED, "template is not registered")
        return self.template

    def dispatch(self, request: DispatchRequest) -> DispatchReceipt:
        if self.crash_before_effect:
            self.crash_before_effect = False
            raise Crash("dispatch: crashed before the effect")
        key = request.idempotency_key
        if key in self.effects:
            self.replays += 1
            return self.effects[key]
        bundle = request.sealed.bundle
        receipt = DispatchReceipt(
            tenant_id=bundle.tenant_id,
            run_id=bundle.run_id,
            seal_digest=request.sealed.seal_digest,
            bundle_digest=bundle.bundle_digest,
            template_id=bundle.template_id,
            template_version=bundle.template_version,
            template_digest=bundle.template_digest,
            dispatch_id=f"dsp:{self.dispatch_salt}{key[4:20]}",
            effect_digest=expected_effect_digest(request.sealed),
            idempotency_key=key,
            dispatcher_id=self.dispatcher_id,
        )
        self.effects[key] = receipt
        self.effect_keys.append(key)
        if self.crash_after_effect:
            self.crash_after_effect = False
            raise Crash("dispatch: crashed after the effect")
        return receipt


class FakeLedgerReader:
    def __init__(self, reader_id: str = "ledger.reader") -> None:
        self.reader_id = reader_id
        self.reads: dict[str, ReconciliationReport] = {}
        self.read_keys: list[str] = []
        self.replays = 0
        self.crash_before_read = False
        self.crash_after_read = False

    def read_reconciliation(self, query) -> ReconciliationReport:
        if self.crash_before_read:
            self.crash_before_read = False
            raise Crash("ledger: crashed before the read")
        key = query.idempotency_key
        if key in self.reads:
            self.replays += 1
            return self.reads[key]
        report = ReconciliationReport(
            tenant_id=query.tenant_id,
            run_id=query.run_id,
            seal_digest=query.seal_digest,
            bundle_digest=query.bundle_digest,
            dispatch_id=query.dispatch_id,
            effect_digest=query.effect_digest,
            entry_digest=digest_of(("ledger.entry.v1", key)),
            ledger_ref=f"led:{key[4:20]}",
            reconciled=True,
            idempotency_key=key,
            reader_id=self.reader_id,
        )
        self.reads[key] = report
        self.read_keys.append(key)
        if self.crash_after_read:
            self.crash_after_read = False
            raise Crash("ledger: crashed after the read")
        return report


class FakeSigner:
    def __init__(self, signer_id: str = "forge.signer") -> None:
        self.signer_id = signer_id
        self.certificates: dict[str, Certificate] = {}
        self.sign_keys: list[str] = []
        self.replays = 0
        self.crash_before_sign = False
        self.crash_after_sign = False

    def sign_and_release(self, request) -> Certificate:
        if self.crash_before_sign:
            self.crash_before_sign = False
            raise Crash("forge: crashed before signing")
        key = request.idempotency_key
        if key in self.certificates:
            self.replays += 1
            return self.certificates[key]
        certificate = Certificate(
            tenant_id=request.tenant_id,
            run_id=request.run_id,
            seal_digest=request.seal_digest,
            reconciliation_digest=request.reconciliation_digest,
            chain_digest=request.chain_digest,
            signer_id=self.signer_id,
            signature="sig:" + digest_of(request.canonical).split(":", 1)[1],
            released=True,
            release_ref=f"rel:{key[4:20]}",
            idempotency_key=key,
        )
        self.certificates[key] = certificate
        self.sign_keys.append(key)
        if self.crash_after_sign:
            self.crash_after_sign = False
            raise Crash("forge: crashed after signing")
        return certificate


class FakeApprovalAuthority:
    def __init__(self, plan: FrozenPlan) -> None:
        self.authority_id = "approval.authority"
        self.plan = plan
        self.granted: set[str] = set()
        self.approvers = {"simulation": "sim.approver", "production": "prod.approver"}
        self.calls = 0

    def grant(self, *stages: Stage) -> None:
        for stage in stages:
            self.granted.add(str(stage))

    def fetch_approval(self, query) -> ApprovalRecord | None:
        self.calls += 1
        stage = str(query.stage)
        if stage not in self.granted:
            return None
        return ApprovalRecord(
            tenant_id=query.tenant_id,
            run_id=query.run_id,
            source_digest=query.source_digest,
            stage=query.stage,
            subject_digest=query.subject_digest,
            predecessor_digest=query.predecessor_digest,
            decision=Decision.APPROVE,
            approver_id=self.approvers[stage],
            idempotency_key=derive_approval_key(
                tenant_id=query.tenant_id,
                run_id=query.run_id,
                source_digest=query.source_digest,
                stage=query.stage,
                subject_digest=query.subject_digest,
                plan_digest=self.plan.plan_digest,
            ),
            authority_id=self.authority_id,
        )


def make_template() -> RegistryTemplate:
    return RegistryTemplate(
        template_id="quarterly_close",
        template_version="1.2.0",
        handle_fingerprint=digest_of_text("registry-handle:quarterly_close@1.2.0"),
        parameter_specs=(
            ParameterSpec(name="region", kind=ValueKind.STRING, allowed_strings=("emea", "namer")),
            ParameterSpec(name="period", kind=ValueKind.INTEGER, minimum=1, maximum=4),
        ),
    )


def make_payload(*, summary: str = "Close the quarter for EMEA", drop: str | None = None):
    body = {
        "template_id": "quarterly_close",
        "template_version": "1.2.0",
        "summary": summary,
        "parameters": [
            {"name": "region", "kind": "string", "value": "emea"},
            {"name": "period", "kind": "integer", "value": 3},
        ],
    }
    if drop is not None:
        body.pop(drop)
    return CanonicalMap.of(body)


class Harness:
    def __init__(
        self,
        *,
        payload: CanonicalMap | None = None,
        repairs: dict[int, CanonicalMap] | None = None,
        store: FakeStore | None = None,
    ) -> None:
        self.template = make_template()
        self.policy_config = PolicyConfig(
            policy_id="m3_default",
            policy_version="1.0.0",
            allowed_tenants=(TENANT,),
            allowed_templates=(("quarterly_close", "1.2.0"),),
            obligations=("dual_approval",),
        )
        self.plan = FrozenPlan(
            request=RunRequest(
                tenant_id=TENANT,
                run_id=RUN_ID,
                source_digest=SOURCE,
                payload=payload if payload is not None else make_payload(),
            ),
            policy_config=self.policy_config,
            budget=BudgetPolicy(),
        )
        self.store = store or FakeStore()
        self.adapter = FakeRepairAdapter(repairs)
        self.dispatcher = FakeDispatcher(self.template)
        self.ledger = FakeLedgerReader()
        self.signer = FakeSigner()
        self.authority = FakeApprovalAuthority(self.plan)
        self.authority.grant(Stage.SIMULATION, Stage.PRODUCTION)
        self.runtime = TrustSpineRuntime(
            store=self.store,
            approval_authority=self.authority,
            prisma=PrismaKernel(self.adapter),
            policy=PolicyKernel(self.policy_config),
            vale=ValeKernel(self.policy_config),
            flow=FlowKernel(self.dispatcher),
            ledger=LedgerKernel(self.ledger),
            forge=ForgeKernel(self.signer),
        )

    def execute(self):
        return self.runtime.execute(self.plan)

    @property
    def checkpoint(self) -> RunCheckpoint:
        return self.store.load_checkpoint(TENANT, RUN_ID)

    def effect_counts(self) -> tuple[int, int, int]:
        return (
            len(self.dispatcher.effect_keys),
            len(self.ledger.read_keys),
            len(self.signer.sign_keys),
        )


def baseline_result():
    harness = Harness()
    return harness, harness.execute()


# ---------------------------------------------------------------------------
# Crash before the effect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "port, flag",
    [("dispatcher", "crash_before_effect"), ("ledger", "crash_before_read"), ("signer", "crash_before_sign")],
)
def test_crash_before_effect_resumes_with_exactly_one_effect(port, flag):
    _, expected = baseline_result()
    harness = Harness()
    setattr(getattr(harness, port), flag, True)

    with pytest.raises(Crash):
        harness.execute()

    # The intent is durable; the effect never happened.
    records = harness.store.load_node_records(TENANT, RUN_ID)
    pending = [record for record in records if record.status is NodeStatus.STARTED]
    assert pending, "a durable intent must precede every effect"
    assert harness.effect_counts()[("dispatcher", "ledger", "signer").index(port)] == 0

    result = harness.execute()
    assert result.digest == expected.digest
    assert harness.effect_counts() == (1, 1, 1)
    assert (harness.dispatcher.replays, harness.ledger.replays, harness.signer.replays) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Crash after the effect, before the success is persisted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "port, flag",
    [("dispatcher", "crash_after_effect"), ("ledger", "crash_after_read"), ("signer", "crash_after_sign")],
)
def test_crash_after_effect_before_persistence_replays_the_same_key(port, flag):
    _, expected = baseline_result()
    harness = Harness()
    setattr(getattr(harness, port), flag, True)

    with pytest.raises(Crash):
        harness.execute()

    result = harness.execute()
    assert result.digest == expected.digest
    # The port produced one real effect and answered the replay from its own
    # idempotency store, under the identical key.
    assert harness.effect_counts() == (1, 1, 1)
    assert getattr(harness, port).replays == 1


@pytest.mark.parametrize("node", list(NODE_PLAN))
def test_crash_after_each_node_resumes_without_duplicate_effects(node):
    baseline, expected = baseline_result()
    records = baseline.store.load_node_records(TENANT, RUN_ID)
    index = 1 + next(
        position
        for position, record in enumerate(records)
        if record.node is node and record.status is NodeStatus.SUCCEEDED
    )

    harness = Harness()
    harness.store.crash_event = "append_node_record"
    harness.store.crash_at = index
    with pytest.raises(Crash):
        harness.execute()
    harness.store.crash_event = None

    result = harness.execute()
    assert result.digest == expected.digest
    assert result.completed_nodes == NODE_PLAN
    assert harness.effect_counts() == (1, 1, 1)
    assert len(harness.store.load_node_records(TENANT, RUN_ID)) == len(records)


def test_crash_at_every_durable_write_still_converges_to_one_result():
    """Drive a crash at *every* checkpoint write of a single run's lifetime."""
    baseline, expected = baseline_result()
    write_count = baseline.store.counts["write_checkpoint"]

    for crash_at in range(1, write_count + 1):
        harness = Harness()
        harness.store.crash_event = "write_checkpoint"
        harness.store.crash_at = crash_at
        with pytest.raises(Crash):
            harness.execute()
        harness.store.crash_event = None

        result = harness.execute()
        assert result.digest == expected.digest
        assert harness.effect_counts() == (1, 1, 1)
        assert harness.checkpoint.phase is RunPhase.CERTIFIED
        assert harness.checkpoint.proves_post_production_model_free


def test_crash_during_repair_counts_each_real_adapter_boundary_entry():
    harness = Harness(payload=make_payload(drop="summary"), repairs={1: make_payload()})
    baseline = Harness(payload=make_payload(drop="summary"), repairs={1: make_payload()})
    expected = baseline.execute()

    records = baseline.store.load_node_records(TENANT, RUN_ID)
    index = 1 + next(
        position
        for position, record in enumerate(records)
        if record.node is NodeName.PRISMA_REPAIR and record.status is NodeStatus.SUCCEEDED
    )
    harness.store.crash_event = "append_node_record"
    harness.store.crash_at = index
    with pytest.raises(Crash):
        harness.execute()
    harness.store.crash_event = None

    result = harness.execute()
    assert result.digest != expected.digest  # the extra real call remains auditable
    assert tuple(
        node for node in result.completed_nodes if node is not NodeName.PRISMA_REPAIR
    ) == NODE_PLAN
    assert result.repair_attempts == 2
    assert result.model_calls_used == 2
    assert len(harness.adapter.calls) == 2
    assert len(set(harness.adapter.calls)) == 1


def test_replayed_repair_calls_cannot_exceed_the_three_entry_budget():
    harness = Harness(payload=make_payload(drop="summary"), repairs={1: make_payload()})
    harness.adapter.crash_after_calls = {1, 2, 3}

    for _ in range(3):
        with pytest.raises(Crash):
            harness.execute()

    with pytest.raises(BudgetError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.REPAIR_BUDGET_EXHAUSTED
    assert len(harness.adapter.calls) == 3
    assert sum(
        record.node is NodeName.PRISMA_REPAIR and record.status is NodeStatus.STARTED
        for record in harness.store.load_node_records(TENANT, RUN_ID)
    ) == 3


# ---------------------------------------------------------------------------
# The production boundary survives crashes
# ---------------------------------------------------------------------------


def test_crash_before_atomic_production_commit_leaves_no_partial_boundary():
    harness = Harness()
    harness.store.crash_event = "commit_production_approval"
    harness.store.crash_at = 1

    with pytest.raises(Crash):
        harness.execute()

    assert len(harness.store.load_approvals(TENANT, RUN_ID)) == 1
    assert not harness.checkpoint.sealed
    assert harness.effect_counts() == (0, 0, 0)

    harness.store.crash_event = None
    result = harness.execute()
    assert result.completed_nodes == NODE_PLAN
    assert harness.checkpoint.sealed
    assert harness.effect_counts() == (1, 1, 1)


def test_sealed_repair_run_resumes_without_reentering_the_model_path():
    harness = Harness(payload=make_payload(drop="summary"), repairs={1: make_payload()})
    harness.dispatcher.crash_before_effect = True

    with pytest.raises(Crash):
        harness.execute()

    assert harness.checkpoint.sealed
    assert len(harness.adapter.calls) == 1
    harness.adapter.responses.clear()
    harness.authority.granted.clear()

    result = harness.execute()
    assert result.model_calls_used == 1
    assert len(harness.adapter.calls) == 1
    assert harness.authority.calls == 2
    assert harness.effect_counts() == (1, 1, 1)


def test_seal_survives_a_crash_and_is_never_reopened():
    _, expected = baseline_result()
    harness = Harness()

    # Find the first checkpoint write that lands *after* the seal write:
    # crashing at write N means write N never happened, so the earliest N whose
    # surviving checkpoint is sealed is the write immediately after the seal.
    seal_write = None
    for candidate in range(1, 60):
        probe = Harness()
        probe.store.crash_event = "write_checkpoint"
        probe.store.crash_at = candidate
        with pytest.raises(Crash):
            probe.execute()
        checkpoint = probe.checkpoint
        if checkpoint is not None and checkpoint.sealed:
            seal_write = candidate
            break
    assert seal_write is not None, "the run must reach a sealed checkpoint"

    harness.store.crash_event = "write_checkpoint"
    harness.store.crash_at = seal_write
    with pytest.raises(Crash):
        harness.execute()
    sealed_checkpoint = harness.checkpoint
    assert sealed_checkpoint.sealed
    assert sealed_checkpoint.model_calls_at_seal == 0

    # The authority withdraws its grants; the run continues from the durable
    # approvals and never asks again.
    harness.store.crash_event = None
    harness.authority.granted.clear()
    calls_before = harness.authority.calls
    result = harness.execute()

    assert harness.authority.calls == calls_before
    assert result.digest == expected.digest
    assert harness.checkpoint.seal_digest == sealed_checkpoint.seal_digest
    assert harness.checkpoint.proves_post_production_model_free
    assert harness.effect_counts() == (1, 1, 1)


# ---------------------------------------------------------------------------
# Conflicting replay
# ---------------------------------------------------------------------------


def test_conflicting_replay_of_an_effect_fails_closed():
    baseline, _ = baseline_result()
    records = baseline.store.load_node_records(TENANT, RUN_ID)
    index = 1 + next(
        position
        for position, record in enumerate(records)
        if record.node is NodeName.FLOW_DISPATCH and record.status is NodeStatus.SUCCEEDED
    )

    harness = Harness()
    harness.store.crash_event = "append_node_record"
    harness.store.crash_at = index
    with pytest.raises(Crash):
        harness.execute()
    harness.store.crash_event = None

    # The durable receipt is readable, but the record was lost.
    assert "receipt" in harness.checkpoint.state
    assert not [
        record
        for record in harness.store.load_node_records(TENANT, RUN_ID)
        if record.node is NodeName.FLOW_DISPATCH and record.status is NodeStatus.SUCCEEDED
    ]

    # A dispatcher that answers the same key differently is not idempotent.
    harness.dispatcher.effects.clear()
    harness.dispatcher.dispatch_salt = "x"
    with pytest.raises(DurabilityError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.IDEMPOTENCY_CONFLICT
    assert harness.signer.sign_keys == []


def test_a_tampered_checkpoint_chain_fails_closed():
    harness = Harness()
    harness.store.crash_event = "write_checkpoint"
    harness.store.crash_at = 6
    with pytest.raises(Crash):
        harness.execute()
    harness.store.crash_event = None

    checkpoint = harness.checkpoint
    harness.store.checkpoints[(TENANT, RUN_ID)] = dataclasses.replace(
        checkpoint, chain_digest=digest_of_text("a chain value that never existed")
    )
    with pytest.raises(DurabilityError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.CHAIN_CORRUPTION
    assert harness.effect_counts() == (0, 0, 0)


def test_a_dropped_journal_record_fails_closed():
    harness = Harness()
    harness.store.crash_event = "write_checkpoint"
    harness.store.crash_at = 8
    with pytest.raises(Crash):
        harness.execute()
    harness.store.crash_event = None

    records = harness.store.node_records[(TENANT, RUN_ID)]
    assert len(records) >= 2
    del records[1]
    with pytest.raises(DurabilityError) as exc:
        harness.execute()
    assert exc.value.code in (FailureCode.CHAIN_CORRUPTION, FailureCode.STATE_CORRUPTION)
    assert harness.effect_counts() == (0, 0, 0)
