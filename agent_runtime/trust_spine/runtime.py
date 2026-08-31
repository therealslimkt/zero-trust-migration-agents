"""The Milestone 3 trust-spine runtime.

This is a *separate, post-plan kernel*. It does not extend, wrap or re-enter
any existing graph: a frozen plan goes in, a certified result comes out, and
the node sequence in between is fixed and closed.

The trace is exactly:

``prisma_validate`` (with up to :data:`~.types.MAX_REPAIRS` ``prisma_repair``
attempts, pre-approval only) -> ``deterministic_policy`` -> ``vale_verify`` ->
*simulation approval* -> *production approval (seals the run)* ->
``flow_dispatch`` -> ``ledger_reconcile`` -> ``forge_certify``.

Two disciplines run through every node:

**Intent before effect.** A ``STARTED`` record is durably appended, and the
checkpoint written, before any port is touched. The record carries the stable
idempotency key the port will be given, so a crash at any point leaves either
"no intent, no effect" or "intent recorded, effect at most once, replayable
under the same key".

**Stable-key replay.** Keys are pure functions of durable material (tenant,
run, node, full plan digest, full proposal digest, seal digest, input digest).
Re-running a node after a crash presents the identical key, so an idempotent
port returns the identical result and no second effect occurs. If a replay
produces something different, the runtime fails closed rather than accept it.

Approvals arrive only through :class:`~.protocols.ApprovalAuthority`. There is
deliberately no ``resume(payload)`` entry point: re-invoking :meth:`
TrustSpineRuntime.execute` with the same frozen plan is the only way to
continue a run, so no caller-supplied blob can ever stand in for an approval.
Clarification (asking a human for more input mid-plan) is a different concern
that belongs to the planning graph, not to this kernel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from .kernels import (
    FlowKernel,
    ForgeKernel,
    LedgerKernel,
    PolicyKernel,
    PrismaKernel,
    SealedExecution,
    ValeKernel,
    assert_no_model_surface,
    build_execution_bundle,
    chain_values,
    node_input_digest,
    replay_chain,
    simulation_subject_digest,
    verify_approval,
)
from .protocols import ApprovalAuthority, StateStore
from .types import (
    EMPTY_MAP,
    ApprovalError,
    ApprovalQuery,
    ApprovalRecord,
    BudgetError,
    CanonicalMap,
    CanonicalValue,
    CertificationError,
    Certificate,
    DispatchReceipt,
    DurabilityError,
    FailureCode,
    FrozenPlan,
    NodeName,
    NodeRecord,
    NodeStatus,
    PolicyDecision,
    ReconciliationReport,
    RecordError,
    RegistryTemplate,
    RepairRequest,
    RunCheckpoint,
    RunPhase,
    RunResult,
    SealedBundle,
    Stage,
    ValeVerdict,
    ValidatedProposal,
    ValidationError,
    derive_approval_key,
    derive_effect_key,
    derive_idempotency_key,
    digest_of,
    error_digest,
    genesis_digest,
    is_sealed_phase,
    phase_index,
    MAX_TRACE_RECORDS,
)

__all__ = ["Journal", "TrustSpineRuntime"]

#: Checkpoint state keys, by the node whose impure output they hold.
_PAYLOAD_KEY: Final[str] = "payload"
_PROPOSAL_KEY: Final[str] = "proposal"
_SEALED_BUNDLE_KEY: Final[str] = "sealed_bundle"
_RECEIPT_KEY: Final[str] = "receipt"
_RECONCILIATION_KEY: Final[str] = "reconciliation"
_CERTIFICATE_KEY: Final[str] = "certificate"


class Journal:
    """Durable, append-only trace for one run.

    The journal owns the hash chain, the checkpoint and the model-call total.
    It holds no model capability of any kind, which is what allows it to be
    carried across the production boundary into :class:`SealedExecution`.
    """

    __slots__ = ("_store", "_plan", "_genesis", "_records", "_approvals", "_chain", "_checkpoint")

    def __init__(self, store: StateStore, plan: FrozenPlan) -> None:
        if not isinstance(plan, FrozenPlan):
            raise RecordError(FailureCode.INVALID_TYPE, "journal requires a FrozenPlan")
        self._store = store
        self._plan = plan
        self._genesis = genesis_digest(plan.tenant_id, plan.run_id, plan.source_digest)
        self._records = self._load_records()
        self._approvals = self._load_approvals()
        values = chain_values(self._genesis, self._records, self._approvals)
        self._chain = values[-1]
        self._checkpoint = self._load_checkpoint(values)

    # -- durable loading ----------------------------------------------------

    def _load_records(self) -> tuple[NodeRecord, ...]:
        loaded = self._store.load_node_records(self._plan.tenant_id, self._plan.run_id)
        if not isinstance(loaded, tuple):
            raise DurabilityError(FailureCode.STATE_CORRUPTION, "records must be a tuple")
        if len(loaded) > MAX_TRACE_RECORDS:
            raise DurabilityError(FailureCode.INVALID_COUNT, "trace exceeds the bounded length")
        for record in loaded:
            if not isinstance(record, NodeRecord):
                raise DurabilityError(FailureCode.STATE_CORRUPTION, "trace holds a non-record")
            if (record.tenant_id, record.run_id, record.source_digest) != (
                self._plan.tenant_id,
                self._plan.run_id,
                self._plan.source_digest,
            ):
                raise DurabilityError(
                    FailureCode.RUN_CONFLICT, "durable record belongs to a different run"
                )
        return loaded

    def _load_approvals(self) -> tuple[ApprovalRecord, ...]:
        loaded = self._store.load_approvals(self._plan.tenant_id, self._plan.run_id)
        if not isinstance(loaded, tuple):
            raise DurabilityError(FailureCode.STATE_CORRUPTION, "approvals must be a tuple")
        if len(loaded) > 2:
            raise DurabilityError(
                FailureCode.APPROVAL_REPLAY, "a run has exactly two approval boundaries"
            )
        expected = (Stage.SIMULATION, Stage.PRODUCTION)
        for index, record in enumerate(loaded):
            if not isinstance(record, ApprovalRecord):
                raise DurabilityError(FailureCode.STATE_CORRUPTION, "approvals hold a non-record")
            if (record.tenant_id, record.run_id, record.source_digest) != (
                self._plan.tenant_id,
                self._plan.run_id,
                self._plan.source_digest,
            ):
                raise DurabilityError(
                    FailureCode.RUN_CONFLICT, "durable approval belongs to a different run"
                )
            if record.stage is not expected[index]:
                raise DurabilityError(
                    FailureCode.APPROVAL_MISMATCH, "approvals are out of stage order"
                )
        keys = [record.idempotency_key for record in loaded]
        if len(set(keys)) != len(keys):
            raise DurabilityError(
                FailureCode.APPROVAL_REPLAY, "the same approval was recorded at both boundaries"
            )
        return loaded

    def _load_checkpoint(self, values: tuple[str, ...]) -> RunCheckpoint:
        loaded = self._store.load_checkpoint(self._plan.tenant_id, self._plan.run_id)
        if loaded is None:
            if self._records or self._approvals:
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION, "durable records exist without a checkpoint"
                )
            fresh = RunCheckpoint(
                tenant_id=self._plan.tenant_id,
                run_id=self._plan.run_id,
                source_digest=self._plan.source_digest,
                request_digest=self._plan.request.request_digest,
                plan_digest=self._plan.plan_digest,
                sequence=0,
                chain_digest=self._genesis,
                state=EMPTY_MAP,
            )
            self._store.write_checkpoint(fresh)
            return fresh
        if not isinstance(loaded, RunCheckpoint):
            raise DurabilityError(FailureCode.STATE_CORRUPTION, "checkpoint is not a RunCheckpoint")
        if (loaded.tenant_id, loaded.run_id) != (self._plan.tenant_id, self._plan.run_id):
            raise DurabilityError(FailureCode.RUN_CONFLICT, "checkpoint belongs to a different run")
        if (
            loaded.request_digest != self._plan.request.request_digest
            or loaded.plan_digest != self._plan.plan_digest
            or loaded.source_digest != self._plan.source_digest
        ):
            raise DurabilityError(
                FailureCode.RUN_CONFLICT,
                "this run id is already bound to a different frozen plan",
            )
        # A crash between "append record" and "write checkpoint" leaves the
        # checkpoint one or more folds behind. That is tolerated, but only if
        # it is genuinely a *prefix* of the recomputed chain.
        if loaded.chain_digest not in values:
            raise DurabilityError(
                FailureCode.CHAIN_CORRUPTION,
                "checkpoint chain is not a prefix of the durable trace",
            )
        caught_up = loaded.advanced(
            phase=loaded.phase,
            chain_digest=self._chain,
            sequence=len(self._records),
            model_calls=self._sum_model_calls(),
        )
        if caught_up != loaded:
            self._store.write_checkpoint(caught_up)
        return caught_up

    def _sum_model_calls(self) -> int:
        return sum(record.model_call_delta for record in self._records)

    # -- read surface -------------------------------------------------------

    @property
    def genesis(self) -> str:
        return self._genesis

    @property
    def chain_digest(self) -> str:
        return self._chain

    @property
    def records(self) -> tuple[NodeRecord, ...]:
        return self._records

    @property
    def approvals(self) -> tuple[ApprovalRecord, ...]:
        return self._approvals

    @property
    def checkpoint(self) -> RunCheckpoint:
        return self._checkpoint

    @property
    def model_calls(self) -> int:
        return self._checkpoint.model_calls

    @property
    def sealed(self) -> bool:
        return self._checkpoint.sealed

    def state_value(self, key: str) -> CanonicalValue:
        return self._checkpoint.state.get(key)

    def ensure_phase(self, phase: RunPhase) -> None:
        """Recover a checkpoint write lost after a durable terminal record."""
        if phase_index(self._checkpoint.phase) < phase_index(phase):
            self._write(phase=phase)

    def terminal_for(self, key: str) -> NodeRecord | None:
        """The terminal record for an idempotency key, if the node finished."""
        for record in self._records:
            if record.idempotency_key == key and record.status is not NodeStatus.STARTED:
                return record
        return None

    def approval_for(self, stage: Stage) -> ApprovalRecord | None:
        for record in self._approvals:
            if record.stage is stage:
                return record
        return None

    def preapproval_attempt_count(self) -> int:
        return sum(
            1
            for record in self._records
            if record.node is NodeName.PRISMA_REPAIR and record.status is NodeStatus.STARTED
        )

    def chain_through(self, node: NodeName, status: NodeStatus) -> str:
        return replay_chain(self._genesis, self._records, self._approvals, stop_after=(node, status))

    # -- append surface -----------------------------------------------------

    def _append(self, record: NodeRecord) -> None:
        if len(self._records) + 1 > MAX_TRACE_RECORDS:
            raise BudgetError(FailureCode.INVALID_COUNT, "trace exceeds the bounded length")
        if self._checkpoint.sealed and record.model_call_delta:
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL,
                "a sealed run cannot journal a model call",
            )
        self._store.append_node_record(record)
        self._records = self._records + (record,)
        self._chain = replay_chain(self._genesis, self._records, self._approvals)

    def _write(
        self,
        *,
        phase: RunPhase,
        state_key: str | None = None,
        state_value: CanonicalValue = None,
        seal_digest: str | None = None,
    ) -> None:
        self._checkpoint = self._checkpoint.advanced(
            phase=phase,
            chain_digest=self._chain,
            sequence=len(self._records),
            model_calls=self._sum_model_calls(),
            state_key=state_key,
            state_value=state_value,
            seal_digest=seal_digest,
        )
        self._store.write_checkpoint(self._checkpoint)

    def begin(
        self,
        *,
        node: NodeName,
        input_digest: str,
        key: str,
        attempt: int,
        model_call_delta: int = 0,
        max_model_calls: int,
    ) -> NodeRecord:
        """Durably record the intent to run a node, before any effect."""
        if self._checkpoint.sealed and model_call_delta:
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL,
                "the production boundary is sealed; a model call is not expressible",
            )
        for record in self._records:
            if record.idempotency_key != key:
                continue
            if record.input_digest != input_digest or record.node is not node:
                raise DurabilityError(
                    FailureCode.IDEMPOTENCY_CONFLICT,
                    "an existing record reuses this key with different input",
                )
            if record.status is NodeStatus.STARTED:
                # Crash after intent, before (or during) the effect: reuse the
                # existing intent for deterministic/side-effect nodes. Model
                # repair is different: each adapter-boundary entry is a real
                # call and must receive its own charged audit record, even
                # when the adapter deduplicates the stable request key.
                if model_call_delta == 0:
                    return record
                continue
        if model_call_delta and self._sum_model_calls() + model_call_delta > max_model_calls:
            raise BudgetError(
                FailureCode.MODEL_BUDGET_EXHAUSTED, "model call budget exhausted"
            )
        record = NodeRecord(
            tenant_id=self._plan.tenant_id,
            run_id=self._plan.run_id,
            source_digest=self._plan.source_digest,
            node=node,
            sequence=len(self._records),
            attempt=attempt,
            predecessor_digest=self._chain,
            input_digest=input_digest,
            output_digest=None,
            error_digest=None,
            idempotency_key=key,
            status=NodeStatus.STARTED,
            model_call_delta=model_call_delta,
        )
        self._append(record)
        self._write(phase=self._checkpoint.phase)
        return record

    def succeed(
        self,
        started: NodeRecord,
        *,
        output_digest: str,
        phase: RunPhase,
        state_key: str | None = None,
        state_value: CanonicalValue = None,
    ) -> NodeRecord:
        # Durable output *before* the success record, never after: that way a
        # persisted SUCCEEDED record always implies its output is readable. A
        # crash in the window leaves an intent with no success, which resumes
        # by re-invoking the port under the same key.
        if state_key is not None:
            self._write(
                phase=self._checkpoint.phase, state_key=state_key, state_value=state_value
            )
        record = NodeRecord(
            tenant_id=started.tenant_id,
            run_id=started.run_id,
            source_digest=started.source_digest,
            node=started.node,
            sequence=len(self._records),
            attempt=started.attempt,
            predecessor_digest=self._chain,
            input_digest=started.input_digest,
            output_digest=output_digest,
            error_digest=None,
            idempotency_key=started.idempotency_key,
            status=NodeStatus.SUCCEEDED,
            model_call_delta=0,
        )
        self._append(record)
        self._write(phase=phase)
        return record

    def fail(self, started: NodeRecord, error: BaseException) -> NodeRecord:
        record = NodeRecord(
            tenant_id=started.tenant_id,
            run_id=started.run_id,
            source_digest=started.source_digest,
            node=started.node,
            sequence=len(self._records),
            attempt=started.attempt,
            predecessor_digest=self._chain,
            input_digest=started.input_digest,
            output_digest=None,
            error_digest=error_digest(error),
            idempotency_key=started.idempotency_key,
            status=NodeStatus.FAILED,
            model_call_delta=0,
        )
        self._append(record)
        self._write(phase=self._checkpoint.phase)
        return record

    def append_approval(self, record: ApprovalRecord, *, phase: RunPhase) -> None:
        if record.stage is Stage.PRODUCTION:
            raise ApprovalError(
                FailureCode.APPROVAL_MISMATCH,
                "production approval cannot be appended outside the atomic seal transaction",
            )
        if self._approval_conflicts(record):
            raise ApprovalError(
                FailureCode.APPROVAL_REPLAY, "this approval was already used at another boundary"
            )
        self._store.append_approval(record)
        self._approvals = self._approvals + (record,)
        self._chain = replay_chain(self._genesis, self._records, self._approvals)
        self._write(phase=phase)

    def _approval_conflicts(self, record: ApprovalRecord) -> bool:
        return any(
            existing.idempotency_key == record.idempotency_key
            or existing.digest == record.digest
            or existing.stage is record.stage
            for existing in self._approvals
        )

    def commit_production_approval(
        self, record: ApprovalRecord, sealed: SealedBundle
    ) -> None:
        """Atomically persist production approval and the irreversible seal."""
        if not isinstance(sealed, SealedBundle):
            raise RecordError(FailureCode.INVALID_TYPE, "sealed must be a SealedBundle")
        if record.stage is not Stage.PRODUCTION:
            raise ApprovalError(
                FailureCode.APPROVAL_MISMATCH,
                "atomic execution seal requires a production approval",
            )
        if self._checkpoint.sealed:
            persisted = self.approval_for(Stage.PRODUCTION)
            stored = self.state_value(_SEALED_BUNDLE_KEY)
            if (
                self._checkpoint.seal_digest != sealed.seal_digest
                or persisted != record
                or stored != sealed.canonical
            ):
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION,
                    "sealed run does not match the production approval bundle",
                )
            return
        if self._approval_conflicts(record):
            raise ApprovalError(
                FailureCode.APPROVAL_REPLAY,
                "this production approval conflicts with durable approval state",
            )
        if record.predecessor_digest != self._chain:
            raise ApprovalError(
                FailureCode.APPROVAL_MISMATCH,
                "production approval is not bound to the current chain",
            )

        next_approvals = self._approvals + (record,)
        next_chain = replay_chain(self._genesis, self._records, next_approvals)
        sealed_checkpoint = self._checkpoint.advanced(
            phase=RunPhase.APPROVED_FOR_EXECUTION,
            chain_digest=next_chain,
            sequence=len(self._records),
            model_calls=self._sum_model_calls(),
            state_key=_SEALED_BUNDLE_KEY,
            state_value=sealed.canonical,
            seal_digest=sealed.seal_digest,
        )
        self._store.commit_production_approval(
            self._checkpoint, record, sealed_checkpoint
        )
        self._approvals = next_approvals
        self._chain = next_chain
        self._checkpoint = sealed_checkpoint


class TrustSpineRuntime:
    """The post-plan trust spine.

    Construction enforces principal *and* object separation: the model
    adapter, approval authority, dispatcher, ledger reader and signer must be
    five distinct principals held by five distinct objects.
    """

    __slots__ = ("_store", "_authority", "_prisma", "_policy", "_vale", "_flow", "_ledger", "_forge")

    def __init__(
        self,
        *,
        store: StateStore,
        approval_authority: ApprovalAuthority,
        prisma: PrismaKernel,
        policy: PolicyKernel,
        vale: ValeKernel,
        flow: FlowKernel,
        ledger: LedgerKernel,
        forge: ForgeKernel,
    ) -> None:
        for name, value, wanted in (
            ("prisma", prisma, PrismaKernel),
            ("policy", policy, PolicyKernel),
            ("vale", vale, ValeKernel),
            ("flow", flow, FlowKernel),
            ("ledger", ledger, LedgerKernel),
            ("forge", forge, ForgeKernel),
        ):
            if not isinstance(value, wanted):
                raise RecordError(FailureCode.INVALID_TYPE, f"{name} must be a {wanted.__name__}")
        for name, port, attributes in (
            ("store", store, ("append_node_record", "load_checkpoint", "store_result")),
            ("approval_authority", approval_authority, ("authority_id", "fetch_approval")),
        ):
            for attribute in attributes:
                if not hasattr(port, attribute):
                    raise RecordError(FailureCode.INVALID_TYPE, f"{name} is not a valid port")
        principals = (
            prisma.adapter_id,
            approval_authority.authority_id,
            flow.dispatcher_id,
            ledger.reader_id,
            forge.signer_id,
        )
        if len(set(principals)) != len(principals):
            raise CertificationError(
                FailureCode.SIGNER_SEPARATION,
                "model, approval, dispatch, ledger and signing principals must be distinct",
            )
        objects = (prisma.adapter, approval_authority, flow.dispatcher, ledger.reader, forge.port)
        if len({id(item) for item in objects}) != len(objects):
            raise CertificationError(
                FailureCode.SIGNER_SEPARATION,
                "an authority-bearing object may not hold two roles",
            )
        self._store = store
        self._authority = approval_authority
        self._prisma = prisma
        self._policy = policy
        self._vale = vale
        self._flow = flow
        self._ledger = ledger
        self._forge = forge

    # -- entry point --------------------------------------------------------

    def execute(self, plan: FrozenPlan) -> RunResult:
        """Run (or resume) one plan to a certified result.

        Re-invoking with the same frozen plan is the *only* resume mechanism.
        There is no generic resume input, so nothing a caller can hand back can
        take the place of an approval.
        """
        if not isinstance(plan, FrozenPlan):
            raise RecordError(
                FailureCode.INVALID_TYPE,
                "the trust spine starts from an immutable FrozenPlan, not a mutable plan object",
            )
        finished = self._store.load_result(plan.tenant_id, plan.run_id)
        if finished is not None:
            if not isinstance(finished, RunResult):
                raise DurabilityError(FailureCode.RESULT_CORRUPTION, "stored result is not a RunResult")
            if finished.request_digest != plan.request.request_digest:
                raise DurabilityError(
                    FailureCode.RUN_CONFLICT, "run id already produced a different result"
                )
            return finished

        journal = Journal(self._store, plan)
        if journal.sealed:
            stored = journal.state_value(_SEALED_BUNDLE_KEY)
            if not isinstance(stored, CanonicalMap):
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION,
                    "sealed checkpoint is missing its immutable execution bundle",
                )
            sealed = SealedBundle.from_canonical(stored, context="sealed_bundle")
            if (
                sealed.tenant_id != plan.tenant_id
                or sealed.run_id != plan.run_id
                or sealed.source_digest != plan.source_digest
                or sealed.seal_digest != journal.checkpoint.seal_digest
            ):
                raise DurabilityError(
                    FailureCode.BINDING_MISMATCH,
                    "sealed execution bundle is not bound to the frozen plan checkpoint",
                )
            return self._execute_sealed(journal, plan, sealed)

        proposal = self._propose(journal, plan)
        decision, template = self._decide(journal, plan, proposal)
        verdict = self._verify(journal, plan, proposal, decision, template)
        simulation = self._approve(
            journal,
            plan,
            stage=Stage.SIMULATION,
            subject_digest=simulation_subject_digest(
                plan_digest=plan.plan_digest,
                proposal_digest=proposal.proposal_digest,
                policy_digest=decision.digest,
                vale_digest=verdict.digest,
            ),
            phase=RunPhase.SIMULATION_APPROVED,
        )
        bundle = build_execution_bundle(
            proposal=proposal,
            decision=decision,
            verdict=verdict,
            simulation_approval=simulation,
        )
        production = self._resolve_production_approval(
            journal,
            plan,
            subject_digest=bundle.bundle_digest,
        )
        if production.digest == simulation.digest or production.subject_digest == simulation.subject_digest:
            raise ApprovalError(
                FailureCode.APPROVAL_REPLAY,
                "the production approval must be a distinct decision on a distinct subject",
            )
        sealed = SealedBundle(bundle=bundle, production_approval_digest=production.digest)
        journal.commit_production_approval(production, sealed)

        return self._execute_sealed(journal, plan, sealed)

    def _execute_sealed(
        self, journal: Journal, plan: FrozenPlan, sealed: SealedBundle
    ) -> RunResult:
        """Resume only the deterministic post-production function graph."""

        # Everything below this line runs on an object that structurally
        # cannot reach a model. The pre-approval kernels are not passed on.
        execution = SealedExecution(
            sealed=sealed,
            plan_digest=plan.plan_digest,
            flow=self._flow,
            ledger=self._ledger,
            forge=self._forge,
        )
        assert_no_model_surface(execution, context="sealed_execution")
        assert_no_model_surface(journal, context="journal")

        receipt = self._dispatch(journal, execution)
        report = self._reconcile(journal, execution, receipt)
        certificate = self._certify(journal, execution, report)
        return self._finalise(
            journal, plan, sealed.bundle.proposal_digest, sealed, certificate
        )

    # -- generic node drivers ----------------------------------------------

    def _pure_node(
        self,
        journal: Journal,
        *,
        node: NodeName,
        input_digest: str,
        key: str,
        attempt: int,
        compute: Callable[[], object],
        phase: RunPhase,
        max_model_calls: int,
        state_key: str | None = None,
    ) -> object:
        """Drive a deterministic node.

        A pure node is *recomputed* on replay and its digest compared to the
        journal, so a run whose deterministic stage no longer reproduces its
        recorded answer fails closed instead of quietly diverging.
        """
        existing = journal.terminal_for(key)
        if existing is not None and existing.status is NodeStatus.SUCCEEDED:
            value = compute()
            if value.digest != existing.output_digest:  # type: ignore[attr-defined]
                raise DurabilityError(
                    FailureCode.RESULT_CORRUPTION, f"{node} is not replay-stable"
                )
            journal.ensure_phase(phase)
            return value
        if existing is not None:
            try:
                compute()
            except Exception as exc:  # noqa: BLE001 - re-raised below
                if error_digest(exc) != existing.error_digest:
                    raise DurabilityError(
                        FailureCode.RESULT_CORRUPTION,
                        f"{node} replayed with a different failure",
                    ) from exc
                raise
            raise DurabilityError(
                FailureCode.RESULT_CORRUPTION, f"{node} previously failed but now succeeds"
            )
        started = journal.begin(
            node=node,
            input_digest=input_digest,
            key=key,
            attempt=attempt,
            max_model_calls=max_model_calls,
        )
        try:
            value = compute()
        except Exception as exc:  # noqa: BLE001 - journalled, then re-raised
            journal.fail(started, exc)
            raise
        journal.succeed(
            started,
            output_digest=value.digest,  # type: ignore[attr-defined]
            phase=phase,
            state_key=state_key,
            state_value=value.canonical if state_key is not None else None,  # type: ignore[attr-defined]
        )
        return value

    def _effect_node(
        self,
        journal: Journal,
        *,
        node: NodeName,
        input_digest: str,
        key: str,
        attempt: int,
        invoke: Callable[[], object],
        decode: Callable[[CanonicalValue], object],
        state_key: str,
        phase: RunPhase,
        max_model_calls: int,
        model_call_delta: int = 0,
        to_digest: Callable[[object], str] = lambda value: value.digest,  # type: ignore[attr-defined]
        to_state: Callable[[object], CanonicalValue] = lambda value: value.canonical,  # type: ignore[attr-defined]
    ) -> object:
        """Drive an externally observable node with intent-before-effect.

        On replay the durable result is decoded from the checkpoint and the
        port is *not* touched again. If the intent was journalled but the
        success was not, the port is re-invoked under the identical key, which
        an idempotent port answers without producing a second effect.
        """
        existing = journal.terminal_for(key)
        if existing is not None and existing.status is NodeStatus.SUCCEEDED:
            stored = journal.state_value(state_key)
            if stored is None:
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION, f"{node} succeeded without durable output"
                )
            value = decode(stored)
            if to_digest(value) != existing.output_digest:
                raise DurabilityError(
                    FailureCode.RESULT_CORRUPTION, f"{node} output does not match the journal"
                )
            journal.ensure_phase(phase)
            return value
        if existing is not None:
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION,
                f"{node} already failed terminally; the run cannot be resumed past it",
            )
        started = journal.begin(
            node=node,
            input_digest=input_digest,
            key=key,
            attempt=attempt,
            model_call_delta=model_call_delta,
            max_model_calls=max_model_calls,
        )
        try:
            value = invoke()
        except Exception as exc:  # noqa: BLE001 - journalled, then re-raised
            journal.fail(started, exc)
            raise
        self._assert_replay_agrees(journal, node, key, value, decode, to_digest, state_key)
        journal.succeed(
            started,
            output_digest=to_digest(value),
            phase=phase,
            state_key=state_key,
            state_value=to_state(value),
        )
        return value

    @staticmethod
    def _assert_replay_agrees(
        journal: Journal,
        node: NodeName,
        key: str,
        value: object,
        decode: Callable[[CanonicalValue], object],
        to_digest: Callable[[object], str],
        state_key: str,
    ) -> None:
        """Fail closed when a re-invoked port answers a key differently.

        A crash between "durable output" and "durable success record" leaves a
        readable previous answer with no success record. The port is re-invoked
        under the identical key, so an idempotent port must return the identical
        answer. If it does not, the run stops rather than pick a winner.
        """
        stored = journal.state_value(state_key)
        if stored is None:
            return
        try:
            previous = decode(stored)
        except DurabilityError:
            return  # no durable answer for *this* key yet
        if to_digest(previous) != to_digest(value):
            raise DurabilityError(
                FailureCode.IDEMPOTENCY_CONFLICT,
                f"{node} replayed key {key[:12]}... with a different result",
            )

    # -- nodes --------------------------------------------------------------

    def _propose(self, journal: Journal, plan: FrozenPlan) -> ValidatedProposal:
        # The loop always restarts from the frozen plan's payload and re-walks
        # the repair chain out of the journal, so attempt numbers, keys and
        # digests are identical on every replay.
        payload: CanonicalMap = plan.payload
        attempt = 0
        while True:
            input_digest = node_input_digest(
                NodeName.PRISMA_VALIDATE, plan.plan_digest, digest_of(payload)
            )
            key = derive_idempotency_key(
                tenant_id=plan.tenant_id,
                run_id=plan.run_id,
                source_digest=plan.source_digest,
                node=NodeName.PRISMA_VALIDATE,
                input_digest=input_digest,
                attempt=attempt,
            )
            candidate = payload
            try:
                return self._pure_node(  # type: ignore[return-value]
                    journal,
                    node=NodeName.PRISMA_VALIDATE,
                    input_digest=input_digest,
                    key=key,
                    attempt=attempt,
                    compute=lambda: self._prisma.validate(plan, candidate),
                    phase=RunPhase.VALIDATED,
                    max_model_calls=plan.budget.max_model_calls,
                    state_key=_PROPOSAL_KEY,
                )
            except ValidationError as failure:
                attempt += 1
                if attempt > plan.budget.max_repairs:
                    raise BudgetError(
                        FailureCode.REPAIR_BUDGET_EXHAUSTED,
                        f"proposal still invalid after {plan.budget.max_repairs} repairs",
                        detail=str(failure.code),
                    ) from failure
                payload = self._repair(journal, plan, payload, attempt, failure)

    def _repair(
        self,
        journal: Journal,
        plan: FrozenPlan,
        payload: CanonicalMap,
        attempt: int,
        failure: ValidationError,
    ) -> CanonicalMap:
        if journal.sealed:  # unreachable by construction; defended anyway
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL, "repair is a pre-approval node only"
            )
        if journal.preapproval_attempt_count() >= plan.budget.max_repairs:
            raise BudgetError(
                FailureCode.REPAIR_BUDGET_EXHAUSTED,
                "repair adapter boundary-entry budget exhausted",
            )
        input_digest = node_input_digest(
            NodeName.PRISMA_REPAIR,
            plan.plan_digest,
            digest_of(payload),
            attempt,
            str(failure.code),
        )
        key = derive_idempotency_key(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            node=NodeName.PRISMA_REPAIR,
            input_digest=input_digest,
            attempt=attempt,
        )
        request = RepairRequest(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            attempt=attempt,
            payload=payload,
            failure_code=failure.code,
            failure_detail=str(failure)[:200],
            idempotency_key=key,
        )

        # Each attempt owns its own durable slot, so a later repair can never
        # overwrite the payload an earlier attempt was journalled against.
        slot = f"a{attempt}"
        stored_payloads = journal.state_value(_PAYLOAD_KEY)
        if stored_payloads is None:
            stored_payloads = EMPTY_MAP
        if not isinstance(stored_payloads, CanonicalMap):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, "stored repair payloads are not a canonical map"
            )

        def decode(stored: CanonicalValue) -> CanonicalMap:
            if not isinstance(stored, CanonicalMap) or slot not in stored:
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION, f"repair attempt {attempt} has no durable payload"
                )
            candidate = stored[slot]
            if not isinstance(candidate, CanonicalMap):
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION, "stored repair payload is not a canonical map"
                )
            return candidate

        repaired = self._effect_node(
            journal,
            node=NodeName.PRISMA_REPAIR,
            input_digest=input_digest,
            key=key,
            attempt=attempt,
            invoke=lambda: self._prisma.repair(request),
            decode=decode,
            state_key=_PAYLOAD_KEY,
            phase=journal.checkpoint.phase,
            max_model_calls=plan.budget.max_model_calls,
            # The intent record charges the call, so a crash mid-call is
            # counted against the budget rather than forgotten.
            model_call_delta=1,
            to_digest=digest_of,
            to_state=lambda value: stored_payloads.updated({slot: value}),
        )
        return repaired  # type: ignore[return-value]

    def _decide(
        self, journal: Journal, plan: FrozenPlan, proposal: ValidatedProposal
    ) -> tuple[PolicyDecision, RegistryTemplate]:
        input_digest = node_input_digest(
            NodeName.DETERMINISTIC_POLICY,
            plan.plan_digest,
            proposal.proposal_digest,
            plan.policy_config.digest,
        )
        key = derive_idempotency_key(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            node=NodeName.DETERMINISTIC_POLICY,
            input_digest=input_digest,
            attempt=0,
        )
        resolved: list[RegistryTemplate] = []

        def compute() -> PolicyDecision:
            template = self._flow.resolve(proposal.template_id, proposal.template_version)
            resolved.append(template)
            return self._policy.decide(proposal, template)

        decision = self._pure_node(
            journal,
            node=NodeName.DETERMINISTIC_POLICY,
            input_digest=input_digest,
            key=key,
            attempt=0,
            compute=compute,
            phase=RunPhase.POLICY_DECIDED,
            max_model_calls=plan.budget.max_model_calls,
        )
        return decision, resolved[-1]  # type: ignore[return-value]

    def _verify(
        self,
        journal: Journal,
        plan: FrozenPlan,
        proposal: ValidatedProposal,
        decision: PolicyDecision,
        template: RegistryTemplate,
    ) -> ValeVerdict:
        input_digest = node_input_digest(
            NodeName.VALE_VERIFY,
            plan.plan_digest,
            proposal.proposal_digest,
            decision.digest,
            template.template_digest,
        )
        key = derive_idempotency_key(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            node=NodeName.VALE_VERIFY,
            input_digest=input_digest,
            attempt=0,
        )
        return self._pure_node(  # type: ignore[return-value]
            journal,
            node=NodeName.VALE_VERIFY,
            input_digest=input_digest,
            key=key,
            attempt=0,
            compute=lambda: self._vale.verify(proposal, decision, template),
            phase=RunPhase.VERIFIED,
            max_model_calls=plan.budget.max_model_calls,
        )

    def _approve(
        self,
        journal: Journal,
        plan: FrozenPlan,
        *,
        stage: Stage,
        subject_digest: str,
        phase: RunPhase,
    ) -> ApprovalRecord:
        if stage is Stage.PRODUCTION:
            raise ApprovalError(
                FailureCode.APPROVAL_MISMATCH,
                "production approval must use the atomic sealing boundary",
            )
        expected_key = derive_approval_key(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            stage=stage,
            subject_digest=subject_digest,
            plan_digest=plan.plan_digest,
        )
        query = ApprovalQuery(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            stage=stage,
            subject_digest=subject_digest,
            predecessor_digest=journal.chain_digest,
        )
        recorded = journal.approval_for(stage)
        if recorded is not None:
            # Already durable: re-verify the bindings, but not against the
            # current chain head (its position was validated on replay).
            verified = verify_approval(
                recorded,
                query=query,
                authority_id=self._authority.authority_id,
                expected_key=expected_key,
                check_predecessor=False,
            )
            journal.ensure_phase(phase)
            return verified
        answer = self._authority.fetch_approval(query)
        if answer is None:
            raise ApprovalError(
                FailureCode.APPROVAL_MISSING,
                f"no server-side {stage} approval for this subject",
            )
        record = verify_approval(
            answer,
            query=query,
            authority_id=self._authority.authority_id,
            expected_key=expected_key,
        )
        journal.append_approval(record, phase=phase)
        return record

    def _resolve_production_approval(
        self,
        journal: Journal,
        plan: FrozenPlan,
        *,
        subject_digest: str,
    ) -> ApprovalRecord:
        """Resolve production approval without persisting it separately.

        Persistence is deliberately deferred to
        :meth:`Journal.commit_production_approval`, which appends the decision
        and seals ``APPROVED_FOR_EXECUTION`` in one store transaction.
        """
        stage = Stage.PRODUCTION
        expected_key = derive_approval_key(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            stage=stage,
            subject_digest=subject_digest,
            plan_digest=plan.plan_digest,
        )
        query = ApprovalQuery(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            stage=stage,
            subject_digest=subject_digest,
            predecessor_digest=journal.chain_digest,
        )
        recorded = journal.approval_for(stage)
        if recorded is not None:
            if not journal.sealed:
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION,
                    "production approval exists without its atomic execution seal",
                )
            return verify_approval(
                recorded,
                query=query,
                authority_id=self._authority.authority_id,
                expected_key=expected_key,
                check_predecessor=False,
            )
        answer = self._authority.fetch_approval(query)
        if answer is None:
            raise ApprovalError(
                FailureCode.APPROVAL_MISSING,
                "no server-side production approval for this subject",
            )
        return verify_approval(
            answer,
            query=query,
            authority_id=self._authority.authority_id,
            expected_key=expected_key,
        )

    def _dispatch(self, journal: Journal, execution: SealedExecution) -> DispatchReceipt:
        input_digest = node_input_digest(
            NodeName.FLOW_DISPATCH, execution.plan_digest, execution.seal_digest
        )
        key = self._effect_key(execution, NodeName.FLOW_DISPATCH, input_digest)
        request = execution.build_dispatch_request(key)
        return self._effect_node(  # type: ignore[return-value]
            journal,
            node=NodeName.FLOW_DISPATCH,
            input_digest=input_digest,
            key=key,
            attempt=0,
            invoke=lambda: execution.flow.dispatch(request),
            decode=lambda stored: DispatchReceipt.from_canonical(_as_map(stored, "receipt")),
            state_key=_RECEIPT_KEY,
            phase=RunPhase.DISPATCHED,
            max_model_calls=0,
        )

    def _reconcile(
        self, journal: Journal, execution: SealedExecution, receipt: DispatchReceipt
    ) -> ReconciliationReport:
        input_digest = node_input_digest(
            NodeName.LEDGER_RECONCILE,
            execution.plan_digest,
            execution.seal_digest,
            receipt.digest,
        )
        key = self._effect_key(execution, NodeName.LEDGER_RECONCILE, input_digest)
        query = execution.build_reconciliation_query(receipt, key)
        return self._effect_node(  # type: ignore[return-value]
            journal,
            node=NodeName.LEDGER_RECONCILE,
            input_digest=input_digest,
            key=key,
            attempt=0,
            invoke=lambda: execution.ledger.reconcile(
                query, sealed=execution.sealed, receipt=receipt
            ),
            decode=lambda stored: ReconciliationReport.from_canonical(
                _as_map(stored, "reconciliation")
            ),
            state_key=_RECONCILIATION_KEY,
            phase=RunPhase.RECONCILED,
            max_model_calls=0,
        )

    def _certify(
        self, journal: Journal, execution: SealedExecution, report: ReconciliationReport
    ) -> Certificate:
        chain_digest = journal.chain_through(NodeName.LEDGER_RECONCILE, NodeStatus.SUCCEEDED)
        input_digest = node_input_digest(
            NodeName.FORGE_CERTIFY, execution.plan_digest, report.digest, chain_digest
        )
        key = self._effect_key(execution, NodeName.FORGE_CERTIFY, input_digest)
        request = execution.build_certification_request(report, chain_digest, key)
        records = journal.records
        approvals = journal.approvals
        return self._effect_node(  # type: ignore[return-value]
            journal,
            node=NodeName.FORGE_CERTIFY,
            input_digest=input_digest,
            key=key,
            attempt=0,
            invoke=lambda: execution.forge.certify(
                request,
                genesis=journal.genesis,
                records=records,
                approvals=approvals,
                sealed=execution.sealed,
                report=report,
            ),
            decode=lambda stored: Certificate.from_canonical(_as_map(stored, "certificate")),
            state_key=_CERTIFICATE_KEY,
            phase=RunPhase.CERTIFIED,
            max_model_calls=0,
        )

    @staticmethod
    def _effect_key(execution: SealedExecution, node: NodeName, input_digest: str) -> str:
        return derive_effect_key(
            tenant_id=execution.tenant_id,
            run_id=execution.run_id,
            source_digest=execution.source_digest,
            node=node,
            plan_digest=execution.plan_digest,
            proposal_digest=execution.proposal_digest,
            seal_digest=execution.seal_digest,
            input_digest=input_digest,
        )

    # -- result -------------------------------------------------------------

    def _finalise(
        self,
        journal: Journal,
        plan: FrozenPlan,
        proposal_digest: str,
        sealed: SealedBundle,
        certificate: Certificate,
    ) -> RunResult:
        checkpoint = journal.checkpoint
        if not checkpoint.proves_post_production_model_free:
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL,
                "checkpoint does not prove a model-free production phase",
            )
        self._assert_post_seal_records_are_model_free(journal)
        result = RunResult(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            request_digest=plan.request.request_digest,
            proposal_digest=proposal_digest,
            seal_digest=sealed.seal_digest,
            chain_digest=journal.chain_digest,
            certificate=certificate,
            approvals=journal.approvals,
            trace=journal.records,
            model_calls_used=journal.model_calls,
            repair_attempts=journal.preapproval_attempt_count(),
        )
        if result.post_production_model_calls:
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL, "trace charges a post-production model call"
            )
        if result.chain_digest != replay_chain(journal.genesis, journal.records, journal.approvals):
            raise DurabilityError(FailureCode.CHAIN_CORRUPTION, "final chain does not verify")
        self._store.store_result(result)
        return result

    @staticmethod
    def _assert_post_seal_records_are_model_free(journal: Journal) -> None:
        """Every journalled record after the seal declares a zero delta."""
        sealed = False
        for record in journal.records:
            if record.node in (
                NodeName.FLOW_DISPATCH,
                NodeName.LEDGER_RECONCILE,
                NodeName.FORGE_CERTIFY,
            ):
                sealed = True
            if sealed and record.model_call_delta != 0:
                raise BudgetError(
                    FailureCode.POST_APPROVAL_MODEL_CALL,
                    f"{record.node} journalled a post-seal model call",
                )
        if not is_sealed_phase(journal.checkpoint.phase):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, "effects ran without a sealed checkpoint"
            )


def _as_map(value: CanonicalValue, where: str) -> CanonicalMap:
    if not isinstance(value, CanonicalMap):
        raise DurabilityError(
            FailureCode.STATE_CORRUPTION, f"durable {where} state is not a canonical map"
        )
    return value
