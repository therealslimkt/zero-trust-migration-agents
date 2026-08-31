"""Closed types and canonical bindings for deterministic approvals."""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import re
from datetime import datetime, timezone
from typing import Protocol


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{2,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{24,256}$")


class ApprovalValidationError(ValueError):
    """A closed approval value is invalid; messages never include its value."""


class ApprovalStage(str, enum.Enum):
    SIMULATION = "simulation"
    PRODUCTION = "production"


class SimulationDecision(str, enum.Enum):
    APPROVE = "approve_simulation"
    REJECT = "reject_simulation"


class ProductionDecision(str, enum.Enum):
    APPROVE = "approve_production"
    REJECT = "reject_production"


class Decision(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"


class TraceEvent(str, enum.Enum):
    REQUEST_OBSERVED = "request_observed"
    AUTHENTICATED_AUTHORITY_READ = "authenticated_authority_read"
    BINDINGS_VERIFIED = "bindings_verified"
    IMMUTABLE_DECISION_RECORDED = "immutable_decision_recorded"
    FAIL_CLOSED_REJECTION = "fail_closed_rejection"


SUCCESS_TRACE = (
    TraceEvent.REQUEST_OBSERVED,
    TraceEvent.AUTHENTICATED_AUTHORITY_READ,
    TraceEvent.BINDINGS_VERIFIED,
    TraceEvent.IMMUTABLE_DECISION_RECORDED,
)
REJECTION_TRACE = (TraceEvent.FAIL_CLOSED_REJECTION,)


def _require(condition: bool, code: str) -> None:
    if condition is not True:
        raise ApprovalValidationError(code)


def _valid_id(value: object) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _valid_time(value: object) -> bool:
    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value.utcoffset().total_seconds() == 0
    )


def canonical_digest(domain: str, fields: tuple[tuple[str, str], ...]) -> str:
    """Hash an unambiguous, ordered and domain-separated byte encoding."""

    _require(_valid_id(domain), "approval_domain")
    framed = bytearray()
    for value in ("m3-approval-v1", domain):
        raw = value.encode("utf-8")
        framed.extend(len(raw).to_bytes(4, "big"))
        framed.extend(raw)
    for key, value in fields:
        _require(type(key) is str and key != "", "approval_digest_key")
        _require(type(value) is str, "approval_digest_value")
        for item in (key, value):
            raw = item.encode("utf-8")
            framed.extend(len(raw).to_bytes(4, "big"))
            framed.extend(raw)
    return "sha256:" + hashlib.sha256(framed).hexdigest()


def nonce_digest(nonce: str) -> str:
    _require(type(nonce) is str and _NONCE.fullmatch(nonce) is not None, "approval_nonce")
    return canonical_digest("approval.nonce", (("nonce", nonce),))


def approval_interrupt_id(
    *,
    tenant_id: str,
    stage: ApprovalStage,
    plan_digest: str,
    release_digest: str,
    artifact_digest: str,
    simulation_record_digest: str | None,
) -> str:
    """Derive an interrupt ID that binds tenant, kind, and approval subject."""

    subject = canonical_digest(
        "approval.subject",
        (
            ("tenant", tenant_id),
            ("stage", stage.value),
            ("plan", plan_digest),
            ("release", release_digest),
            ("artifact", artifact_digest),
            ("simulation", simulation_record_digest or "none"),
        ),
    )
    return "int_" + canonical_digest(
        "approval.interrupt", (("tenant", tenant_id), ("subject", subject))
    ).removeprefix("sha256:")[:40]


@dataclasses.dataclass(frozen=True, slots=True)
class ApprovalCredential:
    """Opaque transport credential supplied outside the approval body."""

    token: str = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        _require(type(self.token) is str and 16 <= len(self.token) <= 4096, "approval_credential")


@dataclasses.dataclass(frozen=True, slots=True)
class AuthorityContext:
    """Server-derived authority and canonical state for one request."""

    actor_id: str
    tenant_id: str
    run_id: str
    stage: ApprovalStage
    plan_digest: str
    release_digest: str
    artifact_digest: str
    interrupt_id: str
    checkpoint_id: str
    audience: str
    approver_count: int
    authenticated: bool
    artifact_present: bool

    def __post_init__(self) -> None:
        for value, code in (
            (self.actor_id, "approval_actor"),
            (self.tenant_id, "approval_tenant"),
            (self.run_id, "approval_run"),
            (self.interrupt_id, "approval_interrupt"),
            (self.checkpoint_id, "approval_checkpoint"),
            (self.audience, "approval_audience"),
        ):
            _require(_valid_id(value), code)
        _require(type(self.stage) is ApprovalStage, "approval_stage")
        for value in (self.plan_digest, self.release_digest, self.artifact_digest):
            _require(_valid_digest(value), "approval_digest")
        _require(type(self.approver_count) is int and self.approver_count >= 0, "approval_approvers")
        _require(type(self.authenticated) is bool, "approval_authenticated")
        _require(type(self.artifact_present) is bool, "approval_artifact_present")


@dataclasses.dataclass(frozen=True, slots=True)
class PendingApproval:
    """Server-issued immutable expectation; never reconstructed from user data."""

    request_id: str
    tenant_id: str
    run_id: str
    stage: ApprovalStage
    plan_digest: str
    release_digest: str
    artifact_digest: str
    interrupt_id: str
    checkpoint_id: str
    nonce_digest: str = dataclasses.field(repr=False)
    issued_at: datetime
    expires_at: datetime
    audience: str
    required_approvers: int
    simulation_record_digest: str | None = None
    request_digest: str = ""

    def __post_init__(self) -> None:
        for value, code in (
            (self.request_id, "approval_request"),
            (self.tenant_id, "approval_tenant"),
            (self.run_id, "approval_run"),
            (self.interrupt_id, "approval_interrupt"),
            (self.checkpoint_id, "approval_checkpoint"),
            (self.audience, "approval_audience"),
        ):
            _require(_valid_id(value), code)
        _require(type(self.stage) is ApprovalStage, "approval_stage")
        for value in (self.plan_digest, self.release_digest, self.artifact_digest, self.nonce_digest):
            _require(_valid_digest(value), "approval_digest")
        _require(_valid_time(self.issued_at) and _valid_time(self.expires_at), "approval_time")
        _require(self.issued_at < self.expires_at, "approval_window")
        _require(type(self.required_approvers) is int and self.required_approvers >= 1, "approval_quorum")
        expected_interrupt = approval_interrupt_id(
            tenant_id=self.tenant_id,
            stage=self.stage,
            plan_digest=self.plan_digest,
            release_digest=self.release_digest,
            artifact_digest=self.artifact_digest,
            simulation_record_digest=self.simulation_record_digest,
        )
        _require(self.interrupt_id == expected_interrupt, "approval_interrupt_binding")
        if self.stage is ApprovalStage.SIMULATION:
            _require(self.simulation_record_digest is None, "approval_simulation_binding")
        else:
            _require(_valid_digest(self.simulation_record_digest), "approval_simulation_binding")
        computed = canonical_digest("approval.request", self.binding_fields())
        if self.request_digest:
            _require(self.request_digest == computed, "approval_request_digest")
        else:
            object.__setattr__(self, "request_digest", computed)

    def binding_fields(self) -> tuple[tuple[str, str], ...]:
        return (
            ("request", self.request_id),
            ("tenant", self.tenant_id),
            ("run", self.run_id),
            ("stage", self.stage.value),
            ("plan", self.plan_digest),
            ("release", self.release_digest),
            ("artifact", self.artifact_digest),
            ("interrupt", self.interrupt_id),
            ("checkpoint", self.checkpoint_id),
            ("nonce", self.nonce_digest),
            ("issued", self.issued_at.isoformat()),
            ("expires", self.expires_at.isoformat()),
            ("audience", self.audience),
            ("quorum", str(self.required_approvers)),
            ("simulation", self.simulation_record_digest or "none"),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class SimulationSubmission:
    request_id: str
    nonce: str = dataclasses.field(repr=False)
    decision: SimulationDecision

    def __post_init__(self) -> None:
        _require(_valid_id(self.request_id), "approval_request")
        _require(type(self.nonce) is str and _NONCE.fullmatch(self.nonce) is not None, "approval_nonce")
        _require(type(self.decision) is SimulationDecision, "approval_decision")


@dataclasses.dataclass(frozen=True, slots=True)
class ProductionSubmission:
    request_id: str
    nonce: str = dataclasses.field(repr=False)
    decision: ProductionDecision

    def __post_init__(self) -> None:
        _require(_valid_id(self.request_id), "approval_request")
        _require(type(self.nonce) is str and _NONCE.fullmatch(self.nonce) is not None, "approval_nonce")
        _require(type(self.decision) is ProductionDecision, "approval_decision")


@dataclasses.dataclass(frozen=True, slots=True)
class ApprovalRecord:
    record_id: str
    request_digest: str
    tenant_id: str
    run_id: str
    stage: ApprovalStage
    plan_digest: str
    release_digest: str
    artifact_digest: str
    simulation_record_digest: str | None
    actor_id: str
    decision: Decision
    recorded_at: datetime
    record_digest: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.record_id, "approval_record"),
            (self.tenant_id, "approval_tenant"),
            (self.run_id, "approval_run"),
            (self.actor_id, "approval_actor"),
        ):
            _require(_valid_id(value), code)
        _require(type(self.stage) is ApprovalStage, "approval_stage")
        _require(type(self.decision) is Decision, "approval_decision")
        _require(_valid_time(self.recorded_at), "approval_recorded_at")
        for value in (
            self.request_digest,
            self.plan_digest,
            self.release_digest,
            self.artifact_digest,
            self.record_digest,
        ):
            _require(_valid_digest(value), "approval_digest")
        if self.stage is ApprovalStage.SIMULATION:
            _require(self.simulation_record_digest is None, "approval_simulation_binding")
        else:
            _require(_valid_digest(self.simulation_record_digest), "approval_simulation_binding")
        expected = canonical_digest(
            "approval.record",
            (
                ("request", self.request_digest),
                ("tenant", self.tenant_id),
                ("run", self.run_id),
                ("stage", self.stage.value),
                ("plan", self.plan_digest),
                ("release", self.release_digest),
                ("artifact", self.artifact_digest),
                ("simulation", self.simulation_record_digest or "none"),
                ("actor", self.actor_id),
                ("decision", self.decision.value),
                ("recorded", self.recorded_at.isoformat()),
            ),
        )
        _require(self.record_digest == expected, "approval_record_digest")
        _require(
            self.record_id == "apr_" + expected.removeprefix("sha256:")[:40],
            "approval_record_id",
        )


@dataclasses.dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    recorded: bool
    record: ApprovalRecord | None
    trace: tuple[TraceEvent, ...]
    public_code: str | None = None
    model_calls: int = 0
    concurrency: int = 1
    graph_depth: int = 0

    def __post_init__(self) -> None:
        _require(type(self.recorded) is bool, "approval_outcome")
        _require((self.record is not None) is self.recorded, "approval_outcome_record")
        _require(
            self.trace == (SUCCESS_TRACE if self.recorded else REJECTION_TRACE),
            "approval_trace",
        )
        _require(type(self.model_calls) is int and self.model_calls == 0, "approval_model_calls")
        _require(type(self.concurrency) is int and self.concurrency == 1, "approval_concurrency")
        _require(type(self.graph_depth) is int and self.graph_depth == 0, "approval_graph_depth")
        if self.recorded:
            _require(self.public_code is None, "approval_public_code")
        else:
            _require(self.public_code == "approval_rejected", "approval_public_code")


class Clock(Protocol):
    def now(self) -> datetime: ...


class ApprovalAuthority(Protocol):
    def resolve(self, *, credential: ApprovalCredential, request_id: str, stage: ApprovalStage) -> AuthorityContext | None: ...


class ApprovalStore(Protocol):
    def load_pending(self, *, request_id: str) -> PendingApproval | None: ...

    def compare_and_record(
        self,
        *,
        pending: PendingApproval,
        authority: AuthorityContext,
        nonce: str,
        decision: Decision,
        now: datetime,
    ) -> ApprovalRecord | None: ...
