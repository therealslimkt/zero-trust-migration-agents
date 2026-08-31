"""Behavioural tests for the Milestone 3 trust spine.

Every port is a local fake. Nothing here reaches a network, a cloud service or
a real model: the kernel under test is an injectable local state machine, and
these tests pin its structural guarantees rather than any provider behaviour.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from agent_runtime.trust_spine import (
    DEFAULT_BUDGET,
    MAX_REPAIRS,
    MODEL_NODES,
    NODE_PLAN,
    SIDE_EFFECT_NODES,
    ApprovalError,
    ApprovalQuery,
    ApprovalRecord,
    BudgetError,
    BudgetPolicy,
    CanonicalMap,
    Certificate,
    CertificationError,
    CertificationRequest,
    Decision,
    DispatchError,
    DispatchReceipt,
    DispatchRequest,
    DurabilityError,
    FailureCode,
    FlowKernel,
    ForgeKernel,
    FrozenPlan,
    Journal,
    LedgerKernel,
    ModelCapable,
    NodeName,
    NodeStatus,
    ParameterSpec,
    PolicyConfig,
    PolicyError,
    PolicyKernel,
    PrismaKernel,
    ReconciliationError,
    ReconciliationReport,
    RecordError,
    RegistryError,
    RegistryTemplate,
    RunCheckpoint,
    RunPhase,
    RunRequest,
    SealedExecution,
    SealedBundle,
    Stage,
    TrustSpineRuntime,
    ValeKernel,
    ValidationError,
    ValueKind,
    assert_no_model_surface,
    derive_approval_key,
    derive_effect_key,
    digest_of,
    digest_of_text,
    expected_effect_digest,
    has_executable_key_name,
    replay_chain,
    validate_payload,
    verify_approval,
)

TENANT = "acme_corp"
RUN_ID = "run_20260830_000001"
SOURCE = digest_of_text("source://milestone3/close")


# ---------------------------------------------------------------------------
# Local fakes (data-only configuration: no fake holds a callable)
# ---------------------------------------------------------------------------


class Crash(BaseException):
    """Simulated process death. Deliberately not an ``Exception``."""


class FakeStore:
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

    def repair(self, request) -> CanonicalMap:
        self.calls.append(request.idempotency_key)
        if request.attempt not in self.responses:
            raise LookupError("no repair candidate for this attempt")
        return self.responses[request.attempt]


class FakeDispatcher:
    def __init__(self, template: RegistryTemplate, dispatcher_id: str = "flow.dispatcher") -> None:
        self.dispatcher_id = dispatcher_id
        self.template = template
        self.effects: dict[str, DispatchReceipt] = {}
        self.effect_keys: list[str] = []
        self.requests: list[DispatchRequest] = []
        self.replays = 0
        self.dispatch_salt = ""
        self.effect_digest_override: str | None = None
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
            raise Crash("dispatch: crashed before the effect")
        self.requests.append(request)
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
            effect_digest=self.effect_digest_override or expected_effect_digest(request.sealed),
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
        self.reconciled = True
        self.effect_digest_override: str | None = None
        self.crash_before_read = False
        self.crash_after_read = False

    def read_reconciliation(self, query) -> ReconciliationReport:
        if self.crash_before_read:
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
            effect_digest=self.effect_digest_override or query.effect_digest,
            entry_digest=digest_of(("ledger.entry.v1", key)),
            ledger_ref=f"led:{key[4:20]}",
            reconciled=self.reconciled,
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
    """Server-side approval reader.

    It answers only the exact question it was asked, and binds its answer to
    the same material the runtime binds its expectations to.
    """

    def __init__(self, plan: FrozenPlan, authority_id: str = "approval.authority") -> None:
        self.authority_id = authority_id
        self.plan = plan
        self.granted: set[str] = set()
        self.rejected: set[str] = set()
        self.approvers = {"simulation": "sim.approver", "production": "prod.approver"}
        self.queries: list = []
        self.replay_simulation_at_production = False

    def grant(self, *stages: Stage) -> None:
        for stage in stages:
            self.granted.add(str(stage))

    def reject(self, *stages: Stage) -> None:
        for stage in stages:
            self.granted.add(str(stage))
            self.rejected.add(str(stage))

    def fetch_approval(self, query) -> ApprovalRecord | None:
        self.queries.append(query)
        stage = str(query.stage)
        if stage not in self.granted:
            return None
        keyed_stage = query.stage
        if self.replay_simulation_at_production and query.stage is Stage.PRODUCTION:
            # Present the simulation decision's key at the production boundary.
            keyed_stage = Stage.SIMULATION
        return ApprovalRecord(
            tenant_id=query.tenant_id,
            run_id=query.run_id,
            source_digest=query.source_digest,
            stage=query.stage,
            subject_digest=query.subject_digest,
            predecessor_digest=query.predecessor_digest,
            decision=Decision.REJECT if stage in self.rejected else Decision.APPROVE,
            approver_id=self.approvers[stage],
            idempotency_key=derive_approval_key(
                tenant_id=query.tenant_id,
                run_id=query.run_id,
                source_digest=query.source_digest,
                stage=keyed_stage,
                subject_digest=query.subject_digest,
                plan_digest=self.plan.plan_digest,
            ),
            authority_id=self.authority_id,
        )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_template() -> RegistryTemplate:
    return RegistryTemplate(
        template_id="quarterly_close",
        template_version="1.2.0",
        handle_fingerprint=digest_of_text("registry-handle:quarterly_close@1.2.0"),
        parameter_specs=(
            ParameterSpec(
                name="region", kind=ValueKind.STRING, allowed_strings=("emea", "namer")
            ),
            ParameterSpec(name="period", kind=ValueKind.INTEGER, minimum=1, maximum=4),
            ParameterSpec(name="dry_run", kind=ValueKind.BOOLEAN, required=False),
        ),
    )


def make_policy_config(**overrides) -> PolicyConfig:
    fields = {
        "policy_id": "m3_default",
        "policy_version": "1.0.0",
        "allowed_tenants": (TENANT,),
        "allowed_templates": (("quarterly_close", "1.2.0"),),
        "obligations": ("dual_approval",),
    }
    fields.update(overrides)
    return PolicyConfig(**fields)


def make_payload(
    *,
    parameters=None,
    summary: str = "Close the quarter for EMEA",
    template_id: str = "quarterly_close",
    template_version: str = "1.2.0",
    extra: dict | None = None,
    drop: str | None = None,
) -> CanonicalMap:
    body: dict = {
        "template_id": template_id,
        "template_version": template_version,
        "summary": summary,
        "parameters": parameters
        if parameters is not None
        else [
            {"name": "region", "kind": "string", "value": "emea"},
            {"name": "period", "kind": "integer", "value": 3},
        ],
    }
    if drop is not None:
        body.pop(drop)
    if extra:
        body.update(extra)
    return CanonicalMap.of(body)


class Harness:
    """One fully injected local runtime plus its fakes."""

    def __init__(
        self,
        *,
        payload: CanonicalMap | None = None,
        policy_config: PolicyConfig | None = None,
        vale_config: PolicyConfig | None = None,
        budget: BudgetPolicy = DEFAULT_BUDGET,
        repairs: dict[int, CanonicalMap] | None = None,
        run_id: str = RUN_ID,
        store: FakeStore | None = None,
        dispatcher_id: str = "flow.dispatcher",
        reader_id: str = "ledger.reader",
        signer_id: str = "forge.signer",
        grant: bool = True,
    ) -> None:
        self.template = make_template()
        self.policy_config = policy_config or make_policy_config()
        self.plan = FrozenPlan(
            request=RunRequest(
                tenant_id=TENANT,
                run_id=run_id,
                source_digest=SOURCE,
                payload=payload if payload is not None else make_payload(),
            ),
            policy_config=self.policy_config,
            budget=budget,
        )
        self.store = store or FakeStore()
        self.adapter = FakeRepairAdapter(repairs)
        self.dispatcher = FakeDispatcher(self.template, dispatcher_id)
        self.ledger = FakeLedgerReader(reader_id)
        self.signer = FakeSigner(signer_id)
        self.authority = FakeApprovalAuthority(self.plan)
        if grant:
            self.authority.grant(Stage.SIMULATION, Stage.PRODUCTION)
        self.runtime = TrustSpineRuntime(
            store=self.store,
            approval_authority=self.authority,
            prisma=PrismaKernel(self.adapter),
            policy=PolicyKernel(self.policy_config),
            vale=ValeKernel(vale_config or self.policy_config),
            flow=FlowKernel(self.dispatcher),
            ledger=LedgerKernel(self.ledger),
            forge=ForgeKernel(self.signer),
        )

    def execute(self):
        return self.runtime.execute(self.plan)

    @property
    def checkpoint(self) -> RunCheckpoint:
        return self.store.load_checkpoint(TENANT, self.plan.run_id)

    def effect_counts(self) -> tuple[int, int, int]:
        return (
            len(self.dispatcher.effect_keys),
            len(self.ledger.read_keys),
            len(self.signer.sign_keys),
        )


# ---------------------------------------------------------------------------
# The fixed trace
# ---------------------------------------------------------------------------


def test_happy_path_runs_the_fixed_trace_once():
    harness = Harness()
    result = harness.execute()

    assert result.completed_nodes == NODE_PLAN
    assert result.repair_attempts == 0
    assert result.model_calls_used == 0
    assert harness.adapter.calls == []
    assert harness.effect_counts() == (1, 1, 1)
    assert result.certificate.released is True
    assert result.certificate.signer_id == "forge.signer"

    stages = tuple(record.stage for record in result.approvals)
    assert stages == (Stage.SIMULATION, Stage.PRODUCTION)
    assert result.approvals[0].subject_digest != result.approvals[1].subject_digest
    assert result.approvals[0].approver_id != result.approvals[1].approver_id
    # The production approval is answered about the execution bundle itself.
    sealed = harness.dispatcher.requests[0].sealed
    assert result.approvals[1].subject_digest == sealed.bundle.bundle_digest
    assert sealed.production_approval_digest == result.approvals[1].digest

    # Intent before effect: every node has a STARTED record before its terminal.
    for node in NODE_PLAN:
        records = result.records_for(node)
        assert [record.status for record in records] == [
            NodeStatus.STARTED,
            NodeStatus.SUCCEEDED,
        ]
    assert harness.checkpoint.phase is RunPhase.CERTIFIED


def test_pre_approval_nodes_precede_every_effect():
    harness = Harness()
    result = harness.execute()
    trace = [record.node for record in result.trace]
    first_effect = min(trace.index(node) for node in SIDE_EFFECT_NODES)
    for node in (NodeName.PRISMA_VALIDATE, NodeName.DETERMINISTIC_POLICY, NodeName.VALE_VERIFY):
        assert max(index for index, item in enumerate(trace) if item is node) < first_effect
    assert NodeName.PRISMA_REPAIR in MODEL_NODES
    assert all(node not in MODEL_NODES for node in SIDE_EFFECT_NODES)


# ---------------------------------------------------------------------------
# Frozen plan
# ---------------------------------------------------------------------------


def test_first_state_must_be_an_immutable_frozen_plan():
    harness = Harness()

    for candidate in (
        {"tenant_id": TENANT, "run_id": RUN_ID},
        harness.plan.request,
        None,
    ):
        with pytest.raises(RecordError) as exc:
            harness.runtime.execute(candidate)
        assert exc.value.code is FailureCode.INVALID_TYPE

    with pytest.raises(dataclasses.FrozenInstanceError):
        harness.plan.request = harness.plan.request  # type: ignore[misc]
    with pytest.raises(RecordError):
        RunRequest(
            tenant_id=TENANT, run_id=RUN_ID, source_digest=SOURCE, payload={"mutable": True}
        )
    with pytest.raises(RecordError) as exc:
        FrozenPlan(
            request=harness.plan.request,
            policy_config=harness.policy_config,
            node_plan=(NodeName.PRISMA_VALIDATE,),
        )
    assert exc.value.code is FailureCode.BINDING_MISMATCH


# ---------------------------------------------------------------------------
# Bounded, pre-approval repair
# ---------------------------------------------------------------------------


def test_repair_is_bounded_and_pre_approval_only():
    harness = Harness(
        payload=make_payload(drop="summary"),
        repairs={
            1: make_payload(summary="unusable summary /etc/passwd"),
            2: make_payload(),
        },
    )
    result = harness.execute()

    assert result.repair_attempts == 2
    assert result.model_calls_used == 2
    assert len(harness.adapter.calls) == 2
    assert len(set(harness.adapter.calls)) == 2

    trace = [record.node for record in result.trace]
    first_effect = min(trace.index(node) for node in SIDE_EFFECT_NODES)
    assert max(index for index, node in enumerate(trace) if node is NodeName.PRISMA_REPAIR) < first_effect
    # The model call is charged on the intent record, never on a result record.
    for record in result.trace:
        if record.model_call_delta:
            assert record.node is NodeName.PRISMA_REPAIR
            assert record.status is NodeStatus.STARTED


def test_repair_budget_exhausts_closed_without_any_effect():
    broken = make_payload(drop="summary")
    harness = Harness(
        payload=broken,
        repairs={attempt: broken for attempt in range(1, MAX_REPAIRS + 1)},
    )
    with pytest.raises(BudgetError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.REPAIR_BUDGET_EXHAUSTED
    assert len(harness.adapter.calls) == MAX_REPAIRS
    assert harness.effect_counts() == (0, 0, 0)
    assert harness.store.load_result(TENANT, RUN_ID) is None
    assert not harness.checkpoint.sealed


def test_global_model_budget_counts_actual_repair_boundary_entries():
    broken = make_payload(drop="summary")
    harness = Harness(
        payload=broken,
        repairs={1: broken, 2: make_payload()},
        budget=BudgetPolicy(max_repairs=3, max_model_calls=1),
    )
    with pytest.raises(BudgetError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.MODEL_BUDGET_EXHAUSTED
    assert len(harness.adapter.calls) == 1
    assert harness.effect_counts() == (0, 0, 0)


def test_zero_repair_budget_surfaces_the_validation_cause():
    harness = Harness(
        payload=make_payload(extra={"command": "run the close job"}),
        budget=BudgetPolicy(max_repairs=0),
    )
    with pytest.raises(BudgetError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.REPAIR_BUDGET_EXHAUSTED
    assert exc.value.__cause__.code is FailureCode.DANGEROUS_KEY
    assert harness.adapter.calls == []


# ---------------------------------------------------------------------------
# Production seal
# ---------------------------------------------------------------------------


def test_production_approval_seals_atomically_and_irreversibly():
    harness = Harness()
    result = harness.execute()
    checkpoint = harness.checkpoint

    assert checkpoint.sealed
    assert checkpoint.seal_digest == result.seal_digest
    assert checkpoint.proves_post_production_model_free
    assert checkpoint.model_calls == checkpoint.model_calls_at_seal == 0
    assert checkpoint.post_seal_model_calls == 0
    assert harness.store.counts["append_approval"] == 1  # simulation only
    assert harness.store.counts["commit_production_approval"] == 1

    with pytest.raises(DurabilityError) as exc:
        checkpoint.advanced(
            phase=RunPhase.VALIDATED,
            chain_digest=checkpoint.chain_digest,
            sequence=checkpoint.sequence,
            model_calls=checkpoint.model_calls,
        )
    assert exc.value.code is FailureCode.STATE_CORRUPTION

    with pytest.raises(DurabilityError):
        checkpoint.advanced(
            phase=RunPhase.CERTIFIED,
            chain_digest=checkpoint.chain_digest,
            sequence=checkpoint.sequence,
            model_calls=checkpoint.model_calls,
            seal_digest=digest_of_text("a different seal"),
        )
    with pytest.raises(BudgetError) as exc:
        checkpoint.advanced(
            phase=RunPhase.CERTIFIED,
            chain_digest=checkpoint.chain_digest,
            sequence=checkpoint.sequence,
            model_calls=checkpoint.model_calls + 1,
        )
    assert exc.value.code is FailureCode.POST_APPROVAL_MODEL_CALL


def test_sealed_resume_revalidates_records_without_touching_approval_authority():
    harness = Harness()
    harness.dispatcher.crash_before_effect = True
    with pytest.raises(Crash):
        harness.execute()
    assert harness.checkpoint.sealed

    class ForbiddenAuthority:
        @property
        def authority_id(self):  # pragma: no cover - access is the failure
            raise AssertionError("sealed resume read approval authority")

        def fetch_approval(self, query):  # pragma: no cover - access is the failure
            raise AssertionError("sealed resume routed a fresh approval")

    harness.runtime._authority = ForbiddenAuthority()
    harness.dispatcher.crash_before_effect = False
    result = harness.execute()
    assert result.seal_digest == harness.checkpoint.seal_digest


def test_sealed_resume_rejects_changed_immutable_approval_authority_binding():
    harness = Harness()
    harness.dispatcher.crash_before_effect = True
    with pytest.raises(Crash):
        harness.execute()
    journal = Journal(harness.store, harness.plan)
    sealed = SealedBundle.from_canonical(journal.state_value("sealed_bundle"))
    simulation, production = journal.approvals
    journal._approvals = (
        simulation,
        dataclasses.replace(production, authority_id="rogue.authority"),
    )
    with pytest.raises(ApprovalError, match="authority bindings changed"):
        TrustSpineRuntime._revalidate_sealed_approvals(journal, harness.plan, sealed)


def test_sealed_checkpoint_cannot_record_a_post_production_model_call():
    harness = Harness()
    harness.execute()
    checkpoint = harness.checkpoint
    with pytest.raises(BudgetError) as exc:
        dataclasses.replace(checkpoint, post_seal_model_calls=1)
    assert exc.value.code is FailureCode.POST_APPROVAL_MODEL_CALL
    with pytest.raises(BudgetError):
        dataclasses.replace(checkpoint, model_calls=1)


def test_every_post_seal_journal_record_is_model_free():
    harness = Harness(payload=make_payload(drop="summary"), repairs={1: make_payload()})
    result = harness.execute()
    assert result.model_calls_used == 1
    assert result.post_production_model_calls == 0

    seen_effect = False
    for record in result.trace:
        if record.node in SIDE_EFFECT_NODES:
            seen_effect = True
        if seen_effect:
            assert record.model_call_delta == 0


# ---------------------------------------------------------------------------
# Structural model-freedom of the sealed path
# ---------------------------------------------------------------------------


def test_sealed_execution_object_has_no_model_surface():
    from agent_runtime.trust_spine import Journal

    harness = Harness()
    harness.execute()

    slots = set(SealedExecution.__slots__)
    assert slots == {"sealed", "plan_digest", "flow", "ledger", "forge"}
    assert not any("model" in name or "adapter" in name or "provider" in name for name in slots)
    assert not any(
        callable(getattr(SealedExecution, name, None))
        for name in ("repair", "complete", "generate", "model", "adapter")
    )

    journal = Journal(harness.store, harness.plan)
    assert_no_model_surface(journal, context="journal")

    # Contrast: the pre-approval kernel and its adapter *are* model-capable,
    # which is exactly why neither may appear on the sealed path.
    assert isinstance(harness.adapter, ModelCapable)
    assert isinstance(PrismaKernel(harness.adapter), ModelCapable)
    with pytest.raises(BudgetError) as exc:
        assert_no_model_surface(PrismaKernel(harness.adapter), context="prisma")
    assert exc.value.code is FailureCode.POST_APPROVAL_MODEL_CALL


def test_model_surface_detection_rejects_smuggled_capabilities():
    @dataclasses.dataclass(frozen=True, slots=True)
    class Smuggled:
        model_provider: object

    @dataclasses.dataclass(frozen=True, slots=True)
    class Nested:
        inner: object

    harness = Harness()
    for candidate in (
        Smuggled(model_provider=harness.adapter),
        Nested(inner=harness.adapter),
    ):
        with pytest.raises(BudgetError) as exc:
            assert_no_model_surface(candidate, context="candidate")
        assert exc.value.code is FailureCode.POST_APPROVAL_MODEL_CALL


def test_model_surface_detection_walks_private_members_and_deep_containers():
    class PrivateMethod:
        def _generate(self):  # pragma: no cover - rejected structurally
            raise AssertionError

    harness = Harness()
    deeply_nested: object = harness.adapter
    for _ in range(12):
        deeply_nested = {"innocent": (deeply_nested,)}

    for candidate in (PrivateMethod(), deeply_nested, {"_model_provider": harness.adapter}):
        with pytest.raises(BudgetError) as exc:
            assert_no_model_surface(candidate, context="private_or_nested", depth=0)
        assert exc.value.code is FailureCode.POST_APPROVAL_MODEL_CALL


def test_sealed_execution_requires_separate_effect_principals():
    harness = Harness()
    result = harness.execute()
    sealed = harness.dispatcher.requests[0].sealed
    assert result.seal_digest == sealed.seal_digest == harness.checkpoint.seal_digest

    healthy = SealedExecution(
        sealed=sealed,
        plan_digest=harness.plan.plan_digest,
        flow=FlowKernel(FakeDispatcher(harness.template)),
        ledger=LedgerKernel(FakeLedgerReader()),
        forge=ForgeKernel(FakeSigner()),
    )
    assert_no_model_surface(healthy, context="sealed_execution")

    with pytest.raises(CertificationError) as exc:
        SealedExecution(
            sealed=sealed,
            plan_digest=harness.plan.plan_digest,
            flow=FlowKernel(FakeDispatcher(harness.template, "same.principal")),
            ledger=LedgerKernel(FakeLedgerReader("same.principal")),
            forge=ForgeKernel(FakeSigner()),
        )
    assert exc.value.code is FailureCode.SIGNER_SEPARATION


def test_runtime_requires_distinct_principals_and_objects():
    harness = Harness()

    class DualRole(FakeDispatcher):
        """One object trying to hold dispatch *and* signing authority."""

        def __init__(self, template):
            super().__init__(template, "dual.role")
            self.signer_id = "forge.signer"
            self.certificates = {}
            self.sign_keys = []

        def sign_and_release(self, request):  # pragma: no cover - construction fails first
            raise AssertionError("must never be reached")

    dual = DualRole(harness.template)
    with pytest.raises(CertificationError) as exc:
        TrustSpineRuntime(
            store=FakeStore(),
            approval_authority=harness.authority,
            prisma=PrismaKernel(harness.adapter),
            policy=PolicyKernel(harness.policy_config),
            vale=ValeKernel(harness.policy_config),
            flow=FlowKernel(dual),
            ledger=LedgerKernel(FakeLedgerReader()),
            forge=ForgeKernel(dual),
        )
    assert exc.value.code is FailureCode.SIGNER_SEPARATION


# ---------------------------------------------------------------------------
# Idempotency keys
# ---------------------------------------------------------------------------


def test_effect_keys_bind_tenant_run_node_plan_and_proposal():
    harness = Harness()
    result = harness.execute()
    base = dict(
        tenant_id=TENANT,
        run_id=RUN_ID,
        source_digest=SOURCE,
        node=NodeName.FLOW_DISPATCH,
        plan_digest=harness.plan.plan_digest,
        proposal_digest=result.proposal_digest,
        seal_digest=result.seal_digest,
        input_digest=digest_of_text("node input"),
    )
    reference = derive_effect_key(**base)
    assert reference == derive_effect_key(**base)

    for field, replacement in (
        ("tenant_id", "other_tenant"),
        ("run_id", "run_20260830_000002"),
        ("node", NodeName.LEDGER_RECONCILE),
        ("plan_digest", digest_of_text("another plan")),
        ("proposal_digest", digest_of_text("another proposal")),
        ("seal_digest", digest_of_text("another seal")),
        ("input_digest", digest_of_text("another input")),
    ):
        assert derive_effect_key(**{**base, field: replacement}) != reference

    # A truncated digest is refused outright; it is never padded or accepted.
    with pytest.raises(RecordError) as exc:
        derive_effect_key(**{**base, "plan_digest": harness.plan.plan_digest[:40]})
    assert exc.value.code is FailureCode.INVALID_DIGEST
    with pytest.raises(RecordError):
        derive_effect_key(**{**base, "node": NodeName.PRISMA_VALIDATE})

    keys = [record.idempotency_key for record in result.trace]
    assert len(set(keys)) == len(NODE_PLAN)  # one stable key per executed node


def test_effect_keys_are_stable_across_independent_runs():
    first = Harness().execute()
    second = Harness(store=FakeStore()).execute()
    assert [record.idempotency_key for record in first.trace] == [
        record.idempotency_key for record in second.trace
    ]
    assert first.chain_digest == second.chain_digest


# ---------------------------------------------------------------------------
# Identifier domain
# ---------------------------------------------------------------------------


def test_identifiers_outside_the_strict_domain_are_refused_not_normalised():
    good = RunRequest(tenant_id=TENANT, run_id=RUN_ID, source_digest=SOURCE, payload=make_payload())
    assert good.tenant_id == TENANT and good.run_id == RUN_ID  # stored verbatim

    bad_runs = (
        RUN_ID[:15],  # too short: a truncated run id is not a run id
        RUN_ID + "\n",  # trailing newline must not slip past the anchor
        " " + RUN_ID,
        RUN_ID.replace("_", "/"),
        RUN_ID.upper(),
        "",
    )
    for run_id in bad_runs:
        with pytest.raises(RecordError) as exc:
            RunRequest(
                tenant_id=TENANT, run_id=run_id, source_digest=SOURCE, payload=make_payload()
            )
        assert exc.value.code in (FailureCode.INVALID_IDENTIFIER, FailureCode.INVALID_TYPE)

    for tenant in ("ACME_CORP", "acme corp", "acme_corp\n", "ac", "acme-corp"):
        with pytest.raises(RecordError):
            RunRequest(
                tenant_id=tenant, run_id=RUN_ID, source_digest=SOURCE, payload=make_payload()
            )

    for source in ("sha256:" + "0" * 63, "SHA256:" + "0" * 64, digest_of_text("x") + "\n"):
        with pytest.raises(RecordError) as exc:
            RunRequest(
                tenant_id=TENANT, run_id=RUN_ID, source_digest=source, payload=make_payload()
            )
        assert exc.value.code is FailureCode.INVALID_DIGEST


def test_collaboration_identifiers_are_domain_checked():
    harness = Harness()
    result = harness.execute()
    receipt = next(iter(harness.dispatcher.effects.values()))
    with pytest.raises(RecordError) as exc:
        dataclasses.replace(receipt, dispatch_id="dsp:x")  # too short to be a reference
    assert exc.value.code is FailureCode.INVALID_IDENTIFIER
    with pytest.raises(RecordError):
        dataclasses.replace(receipt, dispatch_id=receipt.dispatch_id + "\n")
    with pytest.raises(RecordError):
        dataclasses.replace(receipt, dispatcher_id="Flow Dispatcher")
    with pytest.raises(RecordError):
        dataclasses.replace(result.approvals[0], approver_id="sim approver")


# ---------------------------------------------------------------------------
# Flow: registry templates and closed typed parameters only
# ---------------------------------------------------------------------------


def _all_keys(value) -> set[str]:
    if isinstance(value, CanonicalMap):
        keys = set(value.keys())
        for _, item in value.entries:
            keys |= _all_keys(item)
        return keys
    if isinstance(value, tuple):
        keys: set[str] = set()
        for item in value:
            keys |= _all_keys(item)
        return keys
    return set()


def test_flow_only_ever_sees_registry_identity_and_typed_values():
    harness = Harness()
    harness.execute()
    request = harness.dispatcher.requests[0]

    assert set(inspect.signature(DispatchRequest).parameters) == {"sealed", "idempotency_key"}
    for key in _all_keys(request.canonical):
        assert not has_executable_key_name(key), key

    # Only registry-declared, closed typed values reach the dispatcher.
    for binding in request.parameters:
        spec = harness.template.spec_for(binding.name)
        assert spec is not None and spec.accepts(binding.value)
    assert request.template_id == harness.template.template_id
    assert request.template_version == harness.template.template_version

    # The registry handle is only ever an opaque fingerprint, and the caller
    # never sees or supplies it.
    assert harness.template.handle_fingerprint.startswith("sha256:")
    assert "handle_fingerprint" not in _all_keys(request.canonical)


def test_payloads_cannot_smuggle_executable_targets():
    plan = Harness().plan
    dangerous = {
        "command": "close --force",
        "sql": "select 1",
        "module": "os",
        "path": "etc.passwd",
        "image": "alpine",
        "expression": "1 plus 1",
    }
    for key, value in dangerous.items():
        with pytest.raises(ValidationError) as exc:
            validate_payload(plan, make_payload(extra={key: value}))
        assert exc.value.code is FailureCode.DANGEROUS_KEY

    with pytest.raises(ValidationError) as exc:
        validate_payload(
            plan,
            make_payload(
                parameters=[
                    {"name": "region", "kind": "string", "value": "emea; rm -rf /"},
                    {"name": "period", "kind": "integer", "value": 3},
                ]
            ),
        )
    assert exc.value.code is FailureCode.PARAMETER_INVALID

    with pytest.raises(ValidationError) as exc:
        validate_payload(plan, make_payload(summary="see /etc/passwd"))
    assert exc.value.code is FailureCode.DANGEROUS_CONTENT

    with pytest.raises(ValidationError) as exc:
        validate_payload(plan, make_payload(drop="summary"))
    assert exc.value.code is FailureCode.PROPOSAL_INVALID


def test_parameters_outside_the_registry_domain_are_refused():
    undeclared = make_payload(
        parameters=[
            {"name": "region", "kind": "string", "value": "emea"},
            {"name": "period", "kind": "integer", "value": 3},
            {"name": "shell_flag", "kind": "boolean", "value": True},
        ]
    )
    harness = Harness(payload=undeclared, budget=BudgetPolicy(max_repairs=0))
    with pytest.raises(PolicyError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.PARAMETER_NOT_ALLOWED
    assert harness.effect_counts() == (0, 0, 0)

    out_of_domain = make_payload(
        parameters=[
            {"name": "region", "kind": "string", "value": "apac"},
            {"name": "period", "kind": "integer", "value": 3},
        ]
    )
    harness = Harness(payload=out_of_domain, budget=BudgetPolicy(max_repairs=0))
    with pytest.raises(PolicyError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.PARAMETER_INVALID

    out_of_range = make_payload(
        parameters=[
            {"name": "region", "kind": "string", "value": "emea"},
            {"name": "period", "kind": "integer", "value": 9},
        ]
    )
    harness = Harness(payload=out_of_range, budget=BudgetPolicy(max_repairs=0))
    with pytest.raises(PolicyError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.PARAMETER_INVALID


def test_unregistered_template_identity_fails_closed():
    harness = Harness(
        payload=make_payload(template_version="9.9.9"),
        policy_config=make_policy_config(
            allowed_templates=(("quarterly_close", "1.2.0"), ("quarterly_close", "9.9.9"))
        ),
        budget=BudgetPolicy(max_repairs=0),
    )
    with pytest.raises(RegistryError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.TEMPLATE_NOT_REGISTERED
    assert harness.effect_counts() == (0, 0, 0)


# ---------------------------------------------------------------------------
# Policy / Vale
# ---------------------------------------------------------------------------


def test_policy_denies_unlisted_tenant_and_template():
    harness = Harness(
        policy_config=make_policy_config(allowed_tenants=("other_tenant",)),
        budget=BudgetPolicy(max_repairs=0),
    )
    with pytest.raises(PolicyError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.POLICY_DENIED
    assert harness.effect_counts() == (0, 0, 0)


def test_vale_refuses_when_its_independent_view_disagrees():
    harness = Harness(vale_config=make_policy_config(obligations=("single_approval",)))
    with pytest.raises(PolicyError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.VALE_REFUSED
    assert harness.effect_counts() == (0, 0, 0)
    failures = [
        record
        for record in harness.store.load_node_records(TENANT, RUN_ID)
        if record.status is NodeStatus.FAILED
    ]
    assert [record.node for record in failures] == [NodeName.VALE_VERIFY]


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


def test_approval_comes_only_from_the_authority_and_has_no_generic_resume():
    assert not hasattr(TrustSpineRuntime, "resume")
    public = {
        name
        for name in dir(TrustSpineRuntime)
        if not name.startswith("_") and callable(getattr(TrustSpineRuntime, name, None))
    }
    assert public == {"execute"}
    signature = inspect.signature(TrustSpineRuntime.execute)
    assert list(signature.parameters) == ["self", "plan"]


def test_missing_approval_pauses_the_run_and_resumes_on_re_execution():
    harness = Harness(grant=False)

    with pytest.raises(ApprovalError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.APPROVAL_MISSING
    assert harness.effect_counts() == (0, 0, 0)
    assert harness.store.load_approvals(TENANT, RUN_ID) == ()

    harness.authority.grant(Stage.SIMULATION)
    with pytest.raises(ApprovalError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.APPROVAL_MISSING
    assert len(harness.store.load_approvals(TENANT, RUN_ID)) == 1
    assert not harness.checkpoint.sealed

    harness.authority.grant(Stage.PRODUCTION)
    result = harness.execute()
    assert result.completed_nodes == NODE_PLAN
    assert harness.effect_counts() == (1, 1, 1)
    assert len(result.approvals) == 2


def test_rejected_production_approval_stops_the_run():
    harness = Harness(grant=False)
    harness.authority.grant(Stage.SIMULATION)
    harness.authority.reject(Stage.PRODUCTION)
    with pytest.raises(ApprovalError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.APPROVAL_REJECTED
    assert harness.effect_counts() == (0, 0, 0)
    assert not harness.checkpoint.sealed


def test_simulation_approval_cannot_be_replayed_at_production():
    harness = Harness()
    harness.authority.replay_simulation_at_production = True
    with pytest.raises(ApprovalError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.APPROVAL_REPLAY
    assert harness.effect_counts() == (0, 0, 0)
    assert not harness.checkpoint.sealed


def test_approval_bound_to_another_subject_or_authority_is_refused():
    harness = Harness()
    harness.execute()
    approval = harness.store.load_approvals(TENANT, RUN_ID)[1]
    query = ApprovalQuery(
        tenant_id=approval.tenant_id,
        run_id=approval.run_id,
        source_digest=approval.source_digest,
        stage=approval.stage,
        subject_digest=approval.subject_digest,
        predecessor_digest=approval.predecessor_digest,
    )
    verify_approval(
        approval,
        query=query,
        authority_id=harness.authority.authority_id,
        expected_key=approval.idempotency_key,
    )

    for tampered, expected in (
        (
            dataclasses.replace(approval, subject_digest=digest_of_text("another subject")),
            FailureCode.APPROVAL_MISMATCH,
        ),
        (
            dataclasses.replace(approval, authority_id="rogue.authority"),
            FailureCode.APPROVAL_MISMATCH,
        ),
        (
            dataclasses.replace(approval, stage=Stage.SIMULATION),
            FailureCode.APPROVAL_MISMATCH,
        ),
        (dataclasses.replace(approval, decision=Decision.REJECT), FailureCode.APPROVAL_REJECTED),
    ):
        with pytest.raises(ApprovalError) as exc:
            verify_approval(
                tampered,
                query=query,
                authority_id=harness.authority.authority_id,
                expected_key=approval.idempotency_key,
            )
        assert exc.value.code is expected

    with pytest.raises(ApprovalError) as exc:
        verify_approval(
            approval,
            query=query,
            authority_id=harness.authority.authority_id,
            expected_key=derive_approval_key(
                tenant_id=TENANT,
                run_id=RUN_ID,
                source_digest=SOURCE,
                stage=Stage.SIMULATION,
                subject_digest=approval.subject_digest,
                plan_digest=harness.plan.plan_digest,
            ),
        )
    assert exc.value.code is FailureCode.APPROVAL_REPLAY


# ---------------------------------------------------------------------------
# Ledger and Forge
# ---------------------------------------------------------------------------


def test_dispatch_receipt_must_bind_the_sealed_effect():
    harness = Harness()
    harness.dispatcher.effect_digest_override = digest_of_text("some other effect")
    with pytest.raises(DispatchError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.DISPATCH_MISMATCH
    assert harness.effect_counts()[1] == 0


def test_ledger_validates_the_receipt_and_the_sealed_expectations():
    harness = Harness()
    harness.ledger.effect_digest_override = digest_of_text("a different effect")
    with pytest.raises(ReconciliationError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.RECONCILIATION_MISMATCH

    harness = Harness(store=FakeStore(), run_id="run_20260830_000003")
    harness.ledger.reconciled = False
    with pytest.raises(ReconciliationError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.RECONCILIATION_FAILED
    assert len(harness.signer.sign_keys) == 0


def test_forge_validates_the_whole_chain_before_signing():
    from agent_runtime.trust_spine import genesis_digest

    harness = Harness()
    result = harness.execute()
    sealed = harness.dispatcher.requests[0].sealed
    report = next(iter(harness.ledger.reads.values()))
    genesis = genesis_digest(TENANT, RUN_ID, SOURCE)
    records = harness.store.load_node_records(TENANT, RUN_ID)
    approvals = harness.store.load_approvals(TENANT, RUN_ID)
    key = harness.signer.sign_keys[0]

    assert result.certificate.chain_digest == replay_chain(
        genesis, records, approvals, stop_after=(NodeName.LEDGER_RECONCILE, NodeStatus.SUCCEEDED)
    )

    kernel = ForgeKernel(harness.signer)
    request = CertificationRequest(
        tenant_id=TENANT,
        run_id=RUN_ID,
        seal_digest=sealed.seal_digest,
        reconciliation_digest=report.digest,
        chain_digest=result.certificate.chain_digest,
        idempotency_key=key,
    )

    tampered = list(records)
    tampered[1] = dataclasses.replace(tampered[1], output_digest=digest_of_text("forged output"))
    with pytest.raises(DurabilityError) as exc:
        kernel.certify(
            request,
            genesis=genesis,
            records=tuple(tampered),
            approvals=approvals,
            sealed=sealed,
            report=report,
        )
    assert exc.value.code is FailureCode.CHAIN_CORRUPTION

    lying = dataclasses.replace(request, chain_digest=digest_of_text("a chain that never was"))
    with pytest.raises(CertificationError) as exc:
        kernel.certify(
            lying,
            genesis=genesis,
            records=records,
            approvals=approvals,
            sealed=sealed,
            report=report,
        )
    assert exc.value.code is FailureCode.CHAIN_CORRUPTION

    other_seal = dataclasses.replace(
        sealed, production_approval_digest=digest_of_text("some other approval")
    )
    with pytest.raises(CertificationError) as exc:
        kernel.certify(
            request,
            genesis=genesis,
            records=records,
            approvals=approvals,
            sealed=other_seal,
            report=report,
        )
    assert exc.value.code is FailureCode.CERTIFICATION_MISMATCH

    # None of the refusals reached the signer: it still holds the single
    # certificate produced by the successful run.
    assert harness.signer.sign_keys == [key]


# ---------------------------------------------------------------------------
# Replay stability
# ---------------------------------------------------------------------------


def test_completed_run_replays_from_the_stored_result():
    harness = Harness()
    first = harness.execute()
    second = harness.execute()
    assert second.digest == first.digest
    assert harness.effect_counts() == (1, 1, 1)
    assert harness.store.counts["store_result"] == 1


def test_a_different_plan_may_not_reuse_a_live_run_id():
    harness = Harness(grant=False)
    with pytest.raises(ApprovalError):
        harness.execute()

    conflicting = Harness(
        store=harness.store,
        payload=make_payload(summary="A different summary entirely"),
    )
    with pytest.raises(DurabilityError) as exc:
        conflicting.execute()
    assert exc.value.code is FailureCode.RUN_CONFLICT


def test_tampered_journal_record_fails_closed_on_resume():
    harness = Harness(grant=False)
    with pytest.raises(ApprovalError):
        harness.execute()

    records = harness.store.node_records[(TENANT, RUN_ID)]
    records[1] = dataclasses.replace(records[1], input_digest=digest_of_text("tampered input"))

    harness.authority.grant(Stage.SIMULATION, Stage.PRODUCTION)
    with pytest.raises(DurabilityError) as exc:
        harness.execute()
    assert exc.value.code is FailureCode.CHAIN_CORRUPTION
    assert harness.effect_counts() == (0, 0, 0)
