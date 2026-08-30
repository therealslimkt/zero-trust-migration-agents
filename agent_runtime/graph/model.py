"""Typed private state for the catalog-first graph kernel.

These records are deliberately private runtime types.  Public wire records stay
owned by ``contracts/v2``; an event bridge may project this sanitized journal
onto those contracts without placing source rows in workflow state.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,95}$")


class GraphInvariantError(ValueError):
    """A deterministic graph invariant was violated."""


class CatalogProbeKind(str, enum.Enum):
    METADATA = "metadata"
    VECTOR = "vector"
    ACCESS = "access"


class CatalogRoute(str, enum.Enum):
    EXISTING_ASSET = "EXISTING_ASSET"
    NEEDS_INPUT = "NEEDS_INPUT"
    MIGRATE = "MIGRATE"
    FAIL_CLOSED = "FAIL_CLOSED"


class PlanRoute(str, enum.Enum):
    NEEDS_RESEARCH = "NEEDS_RESEARCH"
    NEEDS_INPUT = "NEEDS_INPUT"
    REJECTED = "REJECTED"
    READY = "READY"
    FAIL_CLOSED = "FAIL_CLOSED"


class GraphPhase(str, enum.Enum):
    NEW = "new"
    VALIDATED = "validated"
    PROBED = "probed"
    JOINED = "joined"
    ROUTED = "routed"
    PAUSED = "paused"
    COMPLETE = "complete"
    FAILED = "failed"


class GraphStatus(str, enum.Enum):
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InterruptKind(str, enum.Enum):
    CLARIFICATION = "clarification"
    SIMULATION_APPROVAL = "simulation_approval"
    PRODUCTION_APPROVAL = "production_approval"

    @property
    def resume_channel(self) -> str:
        if self is InterruptKind.CLARIFICATION:
            return "input_endpoint"
        return "approval_endpoint"


@dataclasses.dataclass(frozen=True)
class CatalogProbe:
    kind: CatalogProbeKind
    candidate_count: int = 0
    missing_input: bool = False
    migration_requested: bool = True
    trustworthy: bool = True
    reason_code: str = "OK"

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CatalogProbeKind):
            raise GraphInvariantError("catalog_probe_kind")
        if type(self.candidate_count) is not int or self.candidate_count < 0:
            raise GraphInvariantError("catalog_candidate_count")
        for value in (self.missing_input, self.migration_requested, self.trustworthy):
            if type(value) is not bool:
                raise GraphInvariantError("catalog_probe_boolean")
        if type(self.reason_code) is not str or not self.reason_code:
            raise GraphInvariantError("catalog_reason_code")


@dataclasses.dataclass(frozen=True)
class PlanRouteInput:
    needs_research: bool = False
    needs_input: bool = False
    policy_rejected: bool = False
    ready: bool = False
    trustworthy: bool = True

    def __post_init__(self) -> None:
        values = dataclasses.astuple(self)
        if any(type(value) is not bool for value in values):
            raise GraphInvariantError("plan_route_boolean")


@dataclasses.dataclass(frozen=True)
class GraphEvent:
    sequence: int
    event_type: str
    node_id: str
    operation_id: str
    model_calls: int = 0
    detail: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise GraphInvariantError("event_sequence")
        for value, code in (
            (self.event_type, "event_type"),
            (self.node_id, "event_node"),
            (self.operation_id, "event_operation"),
        ):
            if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
                raise GraphInvariantError(code)
        if type(self.model_calls) is not int or self.model_calls < 0:
            raise GraphInvariantError("event_model_calls")
        if not isinstance(self.detail, Mapping):
            raise GraphInvariantError("event_detail")
        object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))


@dataclasses.dataclass(frozen=True)
class InterruptRequest:
    interrupt_id: str
    kind: InterruptKind
    checkpoint_id: str
    ordinal: int
    subject_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.interrupt_id.startswith("int_") or len(self.interrupt_id) < 16:
            raise GraphInvariantError("interrupt_id")
        if not isinstance(self.kind, InterruptKind):
            raise GraphInvariantError("interrupt_kind")
        if not self.checkpoint_id.startswith("ckpt_"):
            raise GraphInvariantError("interrupt_checkpoint")
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise GraphInvariantError("interrupt_ordinal")
        approval = self.kind is not InterruptKind.CLARIFICATION
        if approval != (self.subject_digest is not None):
            raise GraphInvariantError("interrupt_subject")

    @property
    def resume_channel(self) -> str:
        return self.kind.resume_channel


@dataclasses.dataclass(frozen=True)
class ResumeInput:
    interrupt_id: str
    checkpoint_id: str
    idempotency_key: str
    text: str

    def __post_init__(self) -> None:
        if not self.interrupt_id.startswith("int_"):
            raise GraphInvariantError("resume_interrupt_id")
        if not self.checkpoint_id.startswith("ckpt_"):
            raise GraphInvariantError("resume_checkpoint_id")
        if type(self.idempotency_key) is not str or len(self.idempotency_key) < 8:
            raise GraphInvariantError("resume_idempotency_key")
        if type(self.text) is not str or not self.text or len(self.text) > 2000:
            raise GraphInvariantError("resume_text")

    @property
    def request_digest(self) -> str:
        canonical = "\x00".join(
            (self.interrupt_id, self.checkpoint_id, self.idempotency_key, self.text)
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclasses.dataclass(frozen=True)
class GraphCheckpoint:
    """A typed resumable position; payload state remains in the snapshot store."""

    checkpoint_id: str
    revision: int
    sequence: int
    phase: GraphPhase
    model_calls: int
    resumable: bool

    def __post_init__(self) -> None:
        if not self.checkpoint_id.startswith("ckpt_"):
            raise GraphInvariantError("checkpoint_id")
        if type(self.revision) is not int or self.revision < 0:
            raise GraphInvariantError("checkpoint_revision")
        if type(self.sequence) is not int or self.sequence < 0:
            raise GraphInvariantError("checkpoint_sequence")
        if type(self.model_calls) is not int or self.model_calls < 0:
            raise GraphInvariantError("checkpoint_model_calls")
        if type(self.resumable) is not bool:
            raise GraphInvariantError("checkpoint_resumable")


@dataclasses.dataclass(frozen=True)
class GraphSnapshot:
    tenant_id: str
    run_id: str
    revision: int = 0
    phase: GraphPhase = GraphPhase.NEW
    status: GraphStatus = GraphStatus.RUNNING
    probes: tuple[CatalogProbe, ...] = ()
    catalog_route: CatalogRoute | None = None
    repair_count: int = 0
    pending_interrupt: InterruptRequest | None = None
    consumed_idempotency_keys: frozenset[str] = frozenset()
    resume_digests: tuple[tuple[str, str], ...] = ()
    events: tuple[GraphEvent, ...] = ()

    def __post_init__(self) -> None:
        for value, code in ((self.tenant_id, "tenant_id"), (self.run_id, "run_id")):
            if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
                raise GraphInvariantError(code)
        if type(self.revision) is not int or self.revision < 0:
            raise GraphInvariantError("revision")
        if type(self.repair_count) is not int or not 0 <= self.repair_count <= 3:
            raise GraphInvariantError("repair_count")
        if tuple(event.sequence for event in self.events) != tuple(
            range(1, len(self.events) + 1)
        ):
            raise GraphInvariantError("event_sequence_gap")
        kinds = [probe.kind for probe in self.probes]
        if len(kinds) != len(set(kinds)):
            raise GraphInvariantError("duplicate_probe")
        receipt_keys = [key for key, _ in self.resume_digests]
        if len(receipt_keys) != len(set(receipt_keys)):
            raise GraphInvariantError("duplicate_resume_receipt")
        if frozenset(receipt_keys) != self.consumed_idempotency_keys:
            raise GraphInvariantError("resume_receipt_keys")

    @property
    def model_calls(self) -> int:
        return sum(event.model_calls for event in self.events)

    @property
    def next_sequence(self) -> int:
        return len(self.events) + 1

    @property
    def checkpoint_id(self) -> str:
        return f"ckpt_{self.run_id.replace('_', '')[-12:]}{self.revision:04d}"

    @property
    def checkpoint(self) -> GraphCheckpoint:
        return GraphCheckpoint(
            checkpoint_id=self.checkpoint_id,
            revision=self.revision,
            sequence=len(self.events),
            phase=self.phase,
            model_calls=self.model_calls,
            resumable=self.phase not in {GraphPhase.COMPLETE, GraphPhase.FAILED},
        )
