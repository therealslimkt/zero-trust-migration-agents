"""Deterministic approval evaluator, authority, store, and kernel."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import threading
from datetime import datetime, timezone

from .model import (
    REJECTION_TRACE,
    SUCCESS_TRACE,
    ApprovalAuthority,
    ApprovalCredential,
    ApprovalOutcome,
    ApprovalRecord,
    ApprovalStage,
    ApprovalStore,
    ApprovalValidationError,
    AuthorityContext,
    Clock,
    Decision,
    PendingApproval,
    ProductionDecision,
    ProductionSubmission,
    SimulationDecision,
    SimulationSubmission,
    approval_interrupt_id,
    canonical_digest,
    nonce_digest,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemClock:
    def now(self) -> datetime:
        return _utc_now()


@dataclasses.dataclass(slots=True)
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def issue_pending(
    *,
    request_id: str,
    tenant_id: str,
    run_id: str,
    stage: ApprovalStage,
    plan_digest: str,
    release_digest: str,
    artifact_digest: str,
    checkpoint_id: str,
    nonce: str,
    issued_at: datetime,
    expires_at: datetime,
    audience: str,
    required_approvers: int,
    simulation_record_digest: str | None = None,
) -> PendingApproval:
    """Create a server-side expectation; the nonce itself is never stored."""

    interrupt_id = approval_interrupt_id(
        tenant_id=tenant_id,
        stage=stage,
        plan_digest=plan_digest,
        release_digest=release_digest,
        artifact_digest=artifact_digest,
        simulation_record_digest=simulation_record_digest,
    )
    return PendingApproval(
        request_id=request_id,
        tenant_id=tenant_id,
        run_id=run_id,
        stage=stage,
        plan_digest=plan_digest,
        release_digest=release_digest,
        artifact_digest=artifact_digest,
        interrupt_id=interrupt_id,
        checkpoint_id=checkpoint_id,
        nonce_digest=nonce_digest(nonce),
        issued_at=issued_at,
        expires_at=expires_at,
        audience=audience,
        required_approvers=required_approvers,
        simulation_record_digest=simulation_record_digest,
    )


class DeterministicAdversarialEvaluator:
    """Fixed evaluator/optimizer loop; it has no model or extension hooks.

    Pass one evaluates the complete threat battery.  The optimizer sorts and
    de-duplicates check IDs and verifies the battery itself is complete.  Pass
    two repeats it to catch state disagreement.  Acceptance requires identical
    all-true verdicts in both passes.
    """

    REQUIRED_CHECKS = frozenset(
        {
            "authentication",
            "stage_authority",
            "tenant",
            "run",
            "stage",
            "plan",
            "release",
            "artifact",
            "artifact_present",
            "interrupt",
            "checkpoint",
            "audience",
            "quorum",
            "nonce",
            "issued",
            "expiry",
            "simulation_progression",
        }
    )

    def evaluate(
        self,
        *,
        pending: PendingApproval,
        authority: AuthorityContext,
        nonce: str,
        now: datetime,
        prior_simulation: ApprovalRecord | None,
    ) -> bool:
        def checks() -> dict[str, bool]:
            prior_ok = pending.stage is ApprovalStage.SIMULATION or (
                prior_simulation is not None
                and prior_simulation.stage is ApprovalStage.SIMULATION
                and prior_simulation.decision is Decision.APPROVE
                and prior_simulation.tenant_id == pending.tenant_id
                and prior_simulation.run_id == pending.run_id
                and prior_simulation.plan_digest == pending.plan_digest
                and prior_simulation.release_digest == pending.release_digest
                and prior_simulation.artifact_digest == pending.artifact_digest
                and prior_simulation.record_digest == pending.simulation_record_digest
            )
            return {
                "authentication": authority.authenticated,
                "stage_authority": authority.stage is pending.stage,
                "tenant": hmac.compare_digest(authority.tenant_id, pending.tenant_id),
                "run": hmac.compare_digest(authority.run_id, pending.run_id),
                "stage": authority.stage is pending.stage,
                "plan": hmac.compare_digest(authority.plan_digest, pending.plan_digest),
                "release": hmac.compare_digest(authority.release_digest, pending.release_digest),
                "artifact": hmac.compare_digest(authority.artifact_digest, pending.artifact_digest),
                "artifact_present": authority.artifact_present,
                "interrupt": hmac.compare_digest(authority.interrupt_id, pending.interrupt_id),
                "checkpoint": hmac.compare_digest(authority.checkpoint_id, pending.checkpoint_id),
                "audience": hmac.compare_digest(authority.audience, pending.audience),
                "quorum": authority.approver_count >= pending.required_approvers,
                "nonce": hmac.compare_digest(nonce_digest(nonce), pending.nonce_digest),
                "issued": now >= pending.issued_at,
                "expiry": now < pending.expires_at,
                "simulation_progression": prior_ok,
            }

        previous: tuple[tuple[str, bool], ...] | None = None
        for _ in range(2):
            verdicts = checks()
            # Optimizer: normalize to a stable complete threat program.  An
            # omitted, duplicated, or newly injected check fails closed.
            optimized = tuple(sorted(verdicts.items()))
            if frozenset(verdicts) != self.REQUIRED_CHECKS:
                return False
            if previous is not None and not hmac.compare_digest(repr(previous), repr(optimized)):
                return False
            previous = optimized
        return previous is not None and all(value for _, value in previous)


class InMemoryAuthority:
    """Local reference authority; production must resolve from Cloud SQL."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._contexts: dict[str, AuthorityContext] = {}

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(("m3-authority\x00" + token).encode()).hexdigest()

    def register(self, *, token: str, context: AuthorityContext) -> None:
        if type(token) is not str or len(token) < 16 or type(context) is not AuthorityContext:
            raise ApprovalValidationError("approval_authority_registration")
        with self._lock:
            self._contexts[self._key(token)] = context

    def resolve(
        self, *, credential: ApprovalCredential, request_id: str, stage: ApprovalStage
    ) -> AuthorityContext | None:
        del request_id  # opaque lookup correlation, not an authority field
        if type(credential) is not ApprovalCredential or type(stage) is not ApprovalStage:
            return None
        with self._lock:
            return self._contexts.get(self._key(credential.token))


class InMemoryApprovalStore:
    """Mutex-backed reference implementation of the production transaction.

    Cloud SQL/PostgreSQL must implement the same compare-and-record operation
    in one transaction.  BigQuery is never consulted on the authority path.
    """

    def __init__(self, evaluator: DeterministicAdversarialEvaluator | None = None) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, PendingApproval] = {}
        self._records: dict[tuple[str, str, ApprovalStage], ApprovalRecord] = {}
        self._used_nonces: set[str] = set()
        self._evaluator = evaluator or DeterministicAdversarialEvaluator()

    def issue(self, pending: PendingApproval) -> None:
        if type(pending) is not PendingApproval:
            raise ApprovalValidationError("approval_pending")
        with self._lock:
            if pending.request_id in self._pending:
                raise ApprovalValidationError("approval_request_exists")
            if any(
                issued.nonce_digest == pending.nonce_digest
                for issued in self._pending.values()
            ):
                raise ApprovalValidationError("approval_nonce_exists")
            if pending.stage is ApprovalStage.PRODUCTION:
                prior = self._records.get((pending.tenant_id, pending.run_id, ApprovalStage.SIMULATION))
                if (
                    prior is None
                    or prior.decision is not Decision.APPROVE
                    or prior.record_digest != pending.simulation_record_digest
                    or prior.plan_digest != pending.plan_digest
                    or prior.release_digest != pending.release_digest
                    or prior.artifact_digest != pending.artifact_digest
                ):
                    raise ApprovalValidationError("approval_simulation_progression")
            self._pending[pending.request_id] = pending

    def load_pending(self, *, request_id: str) -> PendingApproval | None:
        with self._lock:
            return self._pending.get(request_id)

    def compare_and_record(
        self,
        *,
        pending: PendingApproval,
        authority: AuthorityContext,
        nonce: str,
        decision: Decision,
        now: datetime,
    ) -> ApprovalRecord | None:
        with self._lock:
            current = self._pending.get(pending.request_id)
            key = (pending.tenant_id, pending.run_id, pending.stage)
            nonce_key = nonce_digest(nonce)
            prior = self._records.get((pending.tenant_id, pending.run_id, ApprovalStage.SIMULATION))
            if (
                current != pending
                or current is None
                or nonce_key in self._used_nonces
                or key in self._records
                or type(decision) is not Decision
                or not self._evaluator.evaluate(
                    pending=current,
                    authority=authority,
                    nonce=nonce,
                    now=now,
                    prior_simulation=prior,
                )
            ):
                return None
            record_fields = (
                ("request", pending.request_digest),
                ("tenant", pending.tenant_id),
                ("run", pending.run_id),
                ("stage", pending.stage.value),
                ("plan", pending.plan_digest),
                ("release", pending.release_digest),
                ("artifact", pending.artifact_digest),
                ("simulation", pending.simulation_record_digest or "none"),
                ("actor", authority.actor_id),
                ("decision", decision.value),
                ("recorded", now.isoformat()),
            )
            record_digest = canonical_digest("approval.record", record_fields)
            record = ApprovalRecord(
                record_id="apr_" + record_digest.removeprefix("sha256:")[:40],
                request_digest=pending.request_digest,
                tenant_id=pending.tenant_id,
                run_id=pending.run_id,
                stage=pending.stage,
                plan_digest=pending.plan_digest,
                release_digest=pending.release_digest,
                artifact_digest=pending.artifact_digest,
                simulation_record_digest=pending.simulation_record_digest,
                actor_id=authority.actor_id,
                decision=decision,
                recorded_at=now,
                record_digest=record_digest,
            )
            self._records[key] = record
            self._used_nonces.add(nonce_key)
            return record

    def record_for(self, *, tenant_id: str, run_id: str, stage: ApprovalStage) -> ApprovalRecord | None:
        with self._lock:
            return self._records.get((tenant_id, run_id, stage))

    @property
    def mutation_count(self) -> int:
        with self._lock:
            return len(self._pending) + len(self._records) + len(self._used_nonces)


class ApprovalKernel:
    """Separate stage entry points; ResumeInput and A2A are not accepted types."""

    def __init__(self, *, authority: ApprovalAuthority, store: ApprovalStore, clock: Clock) -> None:
        self._authority = authority
        self._store = store
        self._clock = clock

    @staticmethod
    def _rejected() -> ApprovalOutcome:
        return ApprovalOutcome(False, None, REJECTION_TRACE, "approval_rejected")

    def approve_simulation(
        self, *, submission: SimulationSubmission, credential: ApprovalCredential
    ) -> ApprovalOutcome:
        if type(submission) is not SimulationSubmission:
            return self._rejected()
        decision = Decision.APPROVE if submission.decision is SimulationDecision.APPROVE else Decision.REJECT
        return self._approve(
            request_id=submission.request_id,
            nonce=submission.nonce,
            stage=ApprovalStage.SIMULATION,
            decision=decision,
            credential=credential,
        )

    def approve_production(
        self, *, submission: ProductionSubmission, credential: ApprovalCredential
    ) -> ApprovalOutcome:
        if type(submission) is not ProductionSubmission:
            return self._rejected()
        decision = Decision.APPROVE if submission.decision is ProductionDecision.APPROVE else Decision.REJECT
        return self._approve(
            request_id=submission.request_id,
            nonce=submission.nonce,
            stage=ApprovalStage.PRODUCTION,
            decision=decision,
            credential=credential,
        )

    def _approve(
        self,
        *,
        request_id: str,
        nonce: str,
        stage: ApprovalStage,
        decision: Decision,
        credential: ApprovalCredential,
    ) -> ApprovalOutcome:
        try:
            pending = self._store.load_pending(request_id=request_id)
            if pending is None or pending.stage is not stage:
                return self._rejected()
            authority = self._authority.resolve(
                credential=credential, request_id=request_id, stage=stage
            )
            if authority is None:
                return self._rejected()
            now = self._clock.now()
            if type(now) is not datetime or now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
                return self._rejected()
            record = self._store.compare_and_record(
                pending=pending,
                authority=authority,
                nonce=nonce,
                decision=decision,
                now=now,
            )
            if record is None:
                return self._rejected()
            return ApprovalOutcome(True, record, SUCCESS_TRACE)
        except (ApprovalValidationError, TypeError, ValueError):
            return self._rejected()
