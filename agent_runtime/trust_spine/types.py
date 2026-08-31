"""Closed, immutable, typed records for the Milestone 3 trust spine.

Everything an authority-bearing boundary touches lives here: canonical JSON,
SHA-256 digesting, the bounded node taxonomy, and the frozen record types that
are chained together from proposal validation through certification.

Design rules enforced by this module:

* No mutable containers on any record field. Sequences are ``tuple``; maps are
  :class:`CanonicalMap` (a sorted, hashable tuple-of-pairs map).
* No ``Any`` on authority-bearing fields. Every field is validated at
  construction: identifier shape, digest shape, bounded counts, cross-record
  binding equality.
* Canonical JSON rejects non-finite numbers, mutable containers and every type
  outside the closed scalar/tuple/map set, so a digest can never be computed
  over an ambiguous or aliasable value.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final, Union

# ---------------------------------------------------------------------------
# Bounded shape constants
# ---------------------------------------------------------------------------

MAX_REPAIRS: Final[int] = 3
MAX_MODEL_CALLS: Final[int] = 30
POST_PRODUCTION_MODEL_CALLS: Final[int] = 0
SIDE_EFFECT_CONCURRENCY: Final[int] = 1
MAX_DEPTH: Final[int] = 0

MAX_CANONICAL_DEPTH: Final[int] = 12
MAX_CONTAINER_LENGTH: Final[int] = 64
MAX_TEXT_LENGTH: Final[int] = 256
MAX_SUMMARY_LENGTH: Final[int] = 200
MAX_PARAMETERS: Final[int] = 16
MAX_TRACE_RECORDS: Final[int] = 512
MAX_SAFE_INT: Final[int] = 2**53 - 1
MAX_PARAMETER_INT: Final[int] = 2**31 - 1

# ---------------------------------------------------------------------------
# Identifier / digest shapes
# ---------------------------------------------------------------------------

# Every pattern is anchored with ``\Z`` (not ``$``) and matched with
# ``fullmatch``: ``$`` also matches before a trailing newline, which would let
# "tenant\n" pass a tenant check. Identifiers are accepted exactly as given --
# the module never strips, lowercases, pads or truncates a candidate to make it
# fit the domain.
DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"sha256:[0-9a-f]{64}\Z")
IDEMPOTENCY_KEY_RE: Final[re.Pattern[str]] = re.compile(r"idk:[0-9a-f]{64}\Z")
SIGNATURE_RE: Final[re.Pattern[str]] = re.compile(r"sig:[0-9a-f]{64}\Z")
TENANT_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_]{2,63}\Z")
# Run ids must be *full*: at least 16 characters, so a truncated prefix of a
# real run id can never satisfy the shape check and slip through a binding.
RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_-]{15,63}\Z")
NAME_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_]{2,63}\Z")
VERSION_RE: Final[re.Pattern[str]] = re.compile(r"\d{1,4}\.\d{1,4}\.\d{1,4}\Z")
PRINCIPAL_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_.\-]{2,63}\Z")
REFERENCE_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:\-]{7,127}\Z")
MAP_KEY_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]{0,63}\Z")
# Parameter/summary text is restricted to a closed, boring character class.
# Nothing in this class can express a path, a command, a URL or an expression.
SAFE_TEXT_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.,:#\-]{0,255}\Z")


# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------


class FailureCode(StrEnum):
    """Closed set of terminal failure reasons."""

    CANONICAL_UNSUPPORTED = "canonical_unsupported"
    CANONICAL_NON_FINITE = "canonical_non_finite"
    INVALID_IDENTIFIER = "invalid_identifier"
    INVALID_DIGEST = "invalid_digest"
    INVALID_COUNT = "invalid_count"
    BINDING_MISMATCH = "binding_mismatch"
    UNKNOWN_FIELD = "unknown_field"
    INVALID_TYPE = "invalid_type"
    DANGEROUS_KEY = "dangerous_key"
    DANGEROUS_CONTENT = "dangerous_content"
    PROPOSAL_INVALID = "proposal_invalid"
    REPAIR_BUDGET_EXHAUSTED = "repair_budget_exhausted"
    MODEL_BUDGET_EXHAUSTED = "model_budget_exhausted"
    POST_APPROVAL_MODEL_CALL = "post_approval_model_call"
    ADAPTER_FAILURE = "adapter_failure"
    POLICY_DENIED = "policy_denied"
    VALE_REFUSED = "vale_refused"
    APPROVAL_MISSING = "approval_missing"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_MISMATCH = "approval_mismatch"
    APPROVAL_REPLAY = "approval_replay"
    TEMPLATE_NOT_REGISTERED = "template_not_registered"
    TEMPLATE_MISMATCH = "template_mismatch"
    PARAMETER_NOT_ALLOWED = "parameter_not_allowed"
    PARAMETER_INVALID = "parameter_invalid"
    DISPATCH_MISMATCH = "dispatch_mismatch"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    RECONCILIATION_FAILED = "reconciliation_failed"
    CERTIFICATION_MISMATCH = "certification_mismatch"
    SIGNER_SEPARATION = "signer_separation"
    CHAIN_CORRUPTION = "chain_corruption"
    STATE_CORRUPTION = "state_corruption"
    RESULT_CORRUPTION = "result_corruption"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    DUPLICATE_EFFECT = "duplicate_effect"
    RUN_CONFLICT = "run_conflict"
    CONCURRENCY_VIOLATION = "concurrency_violation"
    DEPTH_EXCEEDED = "depth_exceeded"


class TrustSpineError(Exception):
    """Base terminal error. Every trust-spine failure is fail-closed."""

    __slots__ = ("code", "detail")

    def __init__(self, code: FailureCode, message: str, *, detail: str = "") -> None:
        super().__init__(f"[{code.value}] {message}" + (f" ({detail})" if detail else ""))
        self.code: FailureCode = code
        self.detail: str = detail

    @property
    def terminal(self) -> bool:
        return True


class CanonicalError(TrustSpineError):
    """Canonical encoding refused a value."""


class RecordError(TrustSpineError):
    """A typed record failed construction-time validation."""


class ValidationError(TrustSpineError):
    """Prisma structured-output validation refused model data."""


class BudgetError(TrustSpineError):
    """A bounded budget was exhausted or violated."""


class PolicyError(TrustSpineError):
    """Deterministic policy or Vale verification refused."""


class ApprovalError(TrustSpineError):
    """Approval boundary refused."""


class RegistryError(TrustSpineError):
    """Template registry identity or parameter refusal."""


class DispatchError(TrustSpineError):
    """Flow dispatch refusal or receipt binding mismatch."""


class ReconciliationError(TrustSpineError):
    """Ledger reconciliation refusal or mismatch."""


class CertificationError(TrustSpineError):
    """Forge certification refusal or signing-separation violation."""


class DurabilityError(TrustSpineError):
    """Durable state is missing, corrupt or conflicting."""


class ConcurrencyError(TrustSpineError):
    """Structural concurrency or recursion depth violation."""


# ---------------------------------------------------------------------------
# Canonical JSON + digesting
# ---------------------------------------------------------------------------

CanonicalScalar = Union[str, int, float, bool, None]
CanonicalValue = Union[CanonicalScalar, "tuple[CanonicalValue, ...]", "CanonicalMap"]


@dataclass(frozen=True, slots=True)
class CanonicalMap:
    """Immutable, hashable, key-sorted string map of canonical values."""

    entries: tuple[tuple[str, CanonicalValue], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise CanonicalError(FailureCode.CANONICAL_UNSUPPORTED, "map entries must be a tuple")
        if len(self.entries) > MAX_CONTAINER_LENGTH:
            raise CanonicalError(FailureCode.INVALID_COUNT, "map exceeds bounded length")
        seen: set[str] = set()
        for entry in self.entries:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise CanonicalError(FailureCode.CANONICAL_UNSUPPORTED, "map entry must be a pair")
            key = entry[0]
            if not isinstance(key, str) or not MAP_KEY_RE.fullmatch(key):
                raise CanonicalError(FailureCode.CANONICAL_UNSUPPORTED, f"invalid map key: {key!r}")
            if key in seen:
                raise CanonicalError(FailureCode.CANONICAL_UNSUPPORTED, f"duplicate map key: {key}")
            seen.add(key)
            _assert_canonical(entry[1], depth=1)
        ordered = tuple(sorted(self.entries, key=lambda pair: pair[0]))
        if ordered != self.entries:
            object.__setattr__(self, "entries", ordered)

    # -- mapping-ish read surface (deliberately read-only) ------------------
    def __getitem__(self, key: str) -> CanonicalValue:
        for entry_key, value in self.entries:
            if entry_key == key:
                return value
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        return any(entry_key == key for entry_key, _ in self.entries)

    def __iter__(self) -> Iterator[str]:
        return iter(key for key, _ in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, key: str, default: CanonicalValue = None) -> CanonicalValue:
        for entry_key, value in self.entries:
            if entry_key == key:
                return value
        return default

    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.entries)

    def updated(self, other: Mapping[str, CanonicalValue]) -> "CanonicalMap":
        """Return a new map with ``other`` merged over this one."""
        merged = dict(self.entries)
        for key, value in other.items():
            merged[key] = freeze(value)
        return CanonicalMap(tuple(sorted(merged.items(), key=lambda pair: pair[0])))

    @classmethod
    def of(cls, mapping: Mapping[str, object]) -> "CanonicalMap":
        """Freeze a plain mapping (lists become tuples, dicts become maps)."""
        return cls(tuple(sorted(((k, freeze(v)) for k, v in mapping.items()), key=lambda p: p[0])))


EMPTY_MAP: Final[CanonicalMap] = CanonicalMap()


def freeze(value: object) -> CanonicalValue:
    """Convert a plain nested structure into canonical immutable values."""
    if value is None or isinstance(value, (str, bool, int, float)):
        _assert_canonical(value, depth=1)
        return value  # type: ignore[return-value]
    if isinstance(value, CanonicalMap):
        return value
    if isinstance(value, (MappingProxyType, Mapping)):
        return CanonicalMap.of({str(k): v for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        if len(value) > MAX_CONTAINER_LENGTH:
            raise CanonicalError(FailureCode.INVALID_COUNT, "sequence exceeds bounded length")
        return tuple(freeze(item) for item in value)
    raise CanonicalError(
        FailureCode.CANONICAL_UNSUPPORTED, f"unsupported value type: {type(value).__name__}"
    )


def _assert_canonical(value: object, *, depth: int) -> None:
    if depth > MAX_CANONICAL_DEPTH:
        raise CanonicalError(FailureCode.INVALID_COUNT, "canonical value exceeds max depth")
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH * 4:
            raise CanonicalError(FailureCode.INVALID_COUNT, "string exceeds bounded length")
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise CanonicalError(FailureCode.INVALID_COUNT, "integer outside JSON-safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalError(FailureCode.CANONICAL_NON_FINITE, "non-finite float rejected")
        return
    if isinstance(value, CanonicalMap):
        return
    if isinstance(value, tuple):
        if len(value) > MAX_CONTAINER_LENGTH:
            raise CanonicalError(FailureCode.INVALID_COUNT, "tuple exceeds bounded length")
        for item in value:
            _assert_canonical(item, depth=depth + 1)
        return
    raise CanonicalError(
        FailureCode.CANONICAL_UNSUPPORTED,
        f"unsupported canonical type: {type(value).__name__}",
    )


def canonical_json(value: CanonicalValue) -> str:
    """Deterministically encode a canonical value.

    Rejects mutable containers (``dict``/``list``/``set``), bytes, arbitrary
    objects, and non-finite floats.
    """
    return _encode(value, depth=0)


def _encode(value: object, *, depth: int) -> str:
    if depth > MAX_CANONICAL_DEPTH:
        raise CanonicalError(FailureCode.INVALID_COUNT, "canonical value exceeds max depth")
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise CanonicalError(FailureCode.INVALID_COUNT, "integer outside JSON-safe range")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalError(FailureCode.CANONICAL_NON_FINITE, "non-finite float rejected")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, CanonicalMap):
        body = ",".join(
            f"{json.dumps(key, ensure_ascii=True)}:{_encode(item, depth=depth + 1)}"
            for key, item in value.entries
        )
        return "{" + body + "}"
    if isinstance(value, MappingProxyType):
        return _encode(CanonicalMap.of(dict(value)), depth=depth)
    if isinstance(value, tuple):
        if len(value) > MAX_CONTAINER_LENGTH:
            raise CanonicalError(FailureCode.INVALID_COUNT, "tuple exceeds bounded length")
        return "[" + ",".join(_encode(item, depth=depth + 1) for item in value) + "]"
    raise CanonicalError(
        FailureCode.CANONICAL_UNSUPPORTED,
        f"unsupported canonical type: {type(value).__name__}",
    )


def digest_of(value: CanonicalValue) -> str:
    """SHA-256 digest of the canonical encoding, prefixed ``sha256:``."""
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_of_text(value: str) -> str:
    """Digest of a raw string (used for source artifacts in tests/tools)."""
    if not isinstance(value, str):
        raise CanonicalError(FailureCode.INVALID_TYPE, "digest_of_text requires str")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def chain_step(previous_digest: str, record_digest: str) -> str:
    """Fold one record digest into the running chain digest."""
    require_digest(previous_digest, "previous_digest")
    require_digest(record_digest, "record_digest")
    return digest_of(("trust_spine.chain.v1", previous_digest, record_digest))


def genesis_digest(tenant_id: str, run_id: str, source_digest: str) -> str:
    """Chain root for a run."""
    return digest_of(("trust_spine.genesis.v1", tenant_id, run_id, source_digest))


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


def require_match(value: object, pattern: re.Pattern[str], field_name: str) -> str:
    """Accept ``value`` exactly as given, or refuse it.

    There is deliberately no normalisation branch here: no ``strip()``, no
    ``lower()``, no prefix slice. A candidate outside the strict dynamic
    identifier domain is a terminal failure, never a repair opportunity.
    """
    if not isinstance(value, str):
        raise RecordError(FailureCode.INVALID_TYPE, f"{field_name} must be a str")
    if not pattern.fullmatch(value):
        raise RecordError(FailureCode.INVALID_IDENTIFIER, f"{field_name} has invalid shape")
    return value


def require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise RecordError(FailureCode.INVALID_TYPE, f"{field_name} must be a str")
    if not DIGEST_RE.fullmatch(value):
        raise RecordError(FailureCode.INVALID_DIGEST, f"{field_name} is not a sha256 digest")
    return value


def require_optional_digest(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return require_digest(value, field_name)


def require_int(value: object, field_name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecordError(FailureCode.INVALID_TYPE, f"{field_name} must be an int")
    if not minimum <= value <= maximum:
        raise RecordError(FailureCode.INVALID_COUNT, f"{field_name} outside [{minimum},{maximum}]")
    return value


def require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise RecordError(FailureCode.INVALID_TYPE, f"{field_name} must be a bool")
    return value


def require_safe_text(value: object, field_name: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str):
        raise ValidationError(FailureCode.INVALID_TYPE, f"{field_name} must be a str")
    if len(value) > max_length:
        raise ValidationError(FailureCode.INVALID_COUNT, f"{field_name} exceeds {max_length} chars")
    if not SAFE_TEXT_RE.fullmatch(value):
        raise ValidationError(
            FailureCode.DANGEROUS_CONTENT, f"{field_name} contains disallowed characters"
        )
    return value


def require_tuple(value: object, field_name: str, *, max_length: int = MAX_CONTAINER_LENGTH) -> tuple:
    if not isinstance(value, tuple):
        raise RecordError(FailureCode.INVALID_TYPE, f"{field_name} must be a tuple")
    if len(value) > max_length:
        raise RecordError(FailureCode.INVALID_COUNT, f"{field_name} exceeds {max_length} items")
    return value


def require_equal(left: object, right: object, field_name: str) -> None:
    if left != right:
        raise RecordError(FailureCode.BINDING_MISMATCH, f"{field_name} binding mismatch")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class NodeName(StrEnum):
    """The complete, closed node taxonomy. No other node may be recorded."""

    PRISMA_VALIDATE = "prisma_validate"
    PRISMA_REPAIR = "prisma_repair"
    DETERMINISTIC_POLICY = "deterministic_policy"
    VALE_VERIFY = "vale_verify"
    FLOW_DISPATCH = "flow_dispatch"
    LEDGER_RECONCILE = "ledger_reconcile"
    FORGE_CERTIFY = "forge_certify"


#: Nodes that may enter a model boundary (pre-approval only).
MODEL_NODES: Final[frozenset[NodeName]] = frozenset({NodeName.PRISMA_REPAIR})
#: Nodes that produce external side effects; concurrency for these is 1.
SIDE_EFFECT_NODES: Final[tuple[NodeName, ...]] = (
    NodeName.FLOW_DISPATCH,
    NodeName.LEDGER_RECONCILE,
    NodeName.FORGE_CERTIFY,
)
#: The fixed bounded graph, in order. Approval boundaries sit between
#: VALE_VERIFY and FLOW_DISPATCH and are recorded as approval records, not nodes.
NODE_PLAN: Final[tuple[NodeName, ...]] = (
    NodeName.PRISMA_VALIDATE,
    NodeName.DETERMINISTIC_POLICY,
    NodeName.VALE_VERIFY,
    NodeName.FLOW_DISPATCH,
    NodeName.LEDGER_RECONCILE,
    NodeName.FORGE_CERTIFY,
)


class NodeStatus(StrEnum):
    STARTED = "started"  # durable intent, persisted before any side effect
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Stage(StrEnum):
    SIMULATION = "simulation"
    PRODUCTION = "production"


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ValueKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class RunPhase(StrEnum):
    """Monotonic lifecycle phase persisted on the durable checkpoint.

    ``APPROVED_FOR_EXECUTION`` is the sealing phase: once a checkpoint reaches
    it the seal digest is fixed and the model-call total is frozen forever.
    """

    PLANNED = "planned"
    VALIDATED = "validated"
    POLICY_DECIDED = "policy_decided"
    VERIFIED = "verified"
    SIMULATION_APPROVED = "simulation_approved"
    APPROVED_FOR_EXECUTION = "approved_for_execution"
    DISPATCHED = "dispatched"
    RECONCILED = "reconciled"
    CERTIFIED = "certified"


#: Total order over :class:`RunPhase`. A checkpoint may only move forward.
PHASE_ORDER: Final[tuple[RunPhase, ...]] = (
    RunPhase.PLANNED,
    RunPhase.VALIDATED,
    RunPhase.POLICY_DECIDED,
    RunPhase.VERIFIED,
    RunPhase.SIMULATION_APPROVED,
    RunPhase.APPROVED_FOR_EXECUTION,
    RunPhase.DISPATCHED,
    RunPhase.RECONCILED,
    RunPhase.CERTIFIED,
)

#: The phase at (and after) which the run is sealed for execution.
SEALING_PHASE: Final[RunPhase] = RunPhase.APPROVED_FOR_EXECUTION


def phase_index(phase: RunPhase) -> int:
    if not isinstance(phase, RunPhase):
        raise RecordError(FailureCode.INVALID_TYPE, "phase must be a RunPhase")
    return PHASE_ORDER.index(phase)


def is_sealed_phase(phase: RunPhase) -> bool:
    return phase_index(phase) >= phase_index(SEALING_PHASE)


# ---------------------------------------------------------------------------
# Canonical map reader (strict rehydration)
# ---------------------------------------------------------------------------


class MapReader:
    """Strict reader for rehydrating records from durable canonical state."""

    __slots__ = ("_map", "_context", "_read")

    def __init__(self, source: CanonicalMap, *, context: str) -> None:
        if not isinstance(source, CanonicalMap):
            raise DurabilityError(FailureCode.STATE_CORRUPTION, f"{context}: expected canonical map")
        self._map = source
        self._context = context
        self._read: set[str] = set()

    def _raw(self, key: str) -> CanonicalValue:
        if key not in self._map:
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}: missing field {key!r}"
            )
        self._read.add(key)
        return self._map[key]

    def text(self, key: str) -> str:
        value = self._raw(key)
        if not isinstance(value, str):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: expected str"
            )
        return value

    def scalar(self, key: str) -> str | int | bool:
        value = self._raw(key)
        if not isinstance(value, (str, int, bool)):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: expected scalar"
            )
        return value

    def optional_text(self, key: str) -> str | None:
        value = self._raw(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: expected str or null"
            )
        return value

    def integer(self, key: str) -> int:
        value = self._raw(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: expected int"
            )
        return value

    def flag(self, key: str) -> bool:
        value = self._raw(key)
        if not isinstance(value, bool):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: expected bool"
            )
        return value

    def submap(self, key: str) -> CanonicalMap:
        value = self._raw(key)
        if not isinstance(value, CanonicalMap):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: expected map"
            )
        return value

    def sequence(self, key: str) -> tuple[CanonicalValue, ...]:
        value = self._raw(key)
        if not isinstance(value, tuple):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: expected tuple"
            )
        return value

    def submaps(self, key: str) -> tuple[CanonicalMap, ...]:
        items = self.sequence(key)
        for item in items:
            if not isinstance(item, CanonicalMap):
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: expected map items"
                )
        return tuple(items)  # type: ignore[arg-type]

    def enum(self, key: str, enum_cls: type[StrEnum]) -> StrEnum:
        raw = self.text(key)
        try:
            return enum_cls(raw)
        except ValueError as exc:
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}.{key}: unknown value {raw!r}"
            ) from exc

    def expect_kind(self, kind: str) -> None:
        actual = self.text("kind")
        if actual != kind:
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, f"{self._context}: expected kind {kind!r}, got {actual!r}"
            )

    def done(self) -> None:
        """Reject unknown fields left unread in durable state."""
        unknown = tuple(key for key in self._map.keys() if key not in self._read)
        if unknown:
            raise DurabilityError(
                FailureCode.UNKNOWN_FIELD, f"{self._context}: unknown fields {unknown!r}"
            )


class _Record:
    """Mixin giving every record a canonical form and a digest."""

    __slots__ = ()

    KIND: ClassVar[str] = "record"

    @property
    def canonical(self) -> CanonicalMap:  # pragma: no cover - abstract
        raise NotImplementedError

    @property
    def digest(self) -> str:
        return digest_of(self.canonical)

    def verify_digest(self, expected: str, field_name: str) -> None:
        if self.digest != expected:
            raise DurabilityError(
                FailureCode.CHAIN_CORRUPTION, f"{field_name}: digest mismatch on rehydrate"
            )


# ---------------------------------------------------------------------------
# Typed parameters and registry templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedValue(_Record):
    """A single typed parameter value. Strings are charset-restricted."""

    KIND: ClassVar[str] = "typed_value"

    kind: ValueKind
    value: str | int | bool

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ValueKind):
            raise RecordError(FailureCode.INVALID_TYPE, "kind must be a ValueKind")
        match self.kind:
            case ValueKind.STRING:
                require_safe_text(self.value, "typed_value.value")
            case ValueKind.INTEGER:
                require_int(
                    self.value,
                    "typed_value.value",
                    minimum=-MAX_PARAMETER_INT,
                    maximum=MAX_PARAMETER_INT,
                )
            case ValueKind.BOOLEAN:
                require_bool(self.value, "typed_value.value")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap((("kind", self.KIND), ("value", self.value), ("value_kind", str(self.kind))))

    @classmethod
    def from_canonical(cls, source: CanonicalMap, *, context: str = "typed_value") -> "TypedValue":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        kind = reader.enum("value_kind", ValueKind)
        raw = reader.scalar("value")
        reader.done()
        return cls(kind=ValueKind(kind), value=raw)


@dataclass(frozen=True, slots=True)
class ParameterBinding(_Record):
    """A registry parameter name bound to a typed value."""

    KIND: ClassVar[str] = "parameter_binding"

    name: str
    value: TypedValue

    def __post_init__(self) -> None:
        require_match(self.name, NAME_RE, "parameter.name")
        if not isinstance(self.value, TypedValue):
            raise RecordError(FailureCode.INVALID_TYPE, "parameter.value must be a TypedValue")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap((("kind", self.KIND), ("name", self.name), ("value", self.value.canonical)))

    @classmethod
    def from_canonical(
        cls, source: CanonicalMap, *, context: str = "parameter_binding"
    ) -> "ParameterBinding":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        name = reader.text("name")
        value = TypedValue.from_canonical(reader.submap("value"), context=f"{context}.value")
        reader.done()
        return cls(name=name, value=value)


@dataclass(frozen=True, slots=True)
class ParameterSpec(_Record):
    """Registry-owned specification for one parameter.

    String parameters must carry a closed allowlist of values, so a caller can
    never introduce free-form string content through a parameter.
    """

    KIND: ClassVar[str] = "parameter_spec"

    name: str
    kind: ValueKind
    required: bool = True
    allowed_strings: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int = 0

    def __post_init__(self) -> None:
        require_match(self.name, NAME_RE, "parameter_spec.name")
        if not isinstance(self.kind, ValueKind):
            raise RecordError(FailureCode.INVALID_TYPE, "parameter_spec.kind must be a ValueKind")
        require_bool(self.required, "parameter_spec.required")
        require_tuple(self.allowed_strings, "parameter_spec.allowed_strings", max_length=32)
        if self.kind is ValueKind.STRING:
            if not self.allowed_strings:
                raise RecordError(
                    FailureCode.PARAMETER_INVALID,
                    "string parameters require a closed allowlist",
                )
            for candidate in self.allowed_strings:
                require_safe_text(candidate, "parameter_spec.allowed_strings[]")
            if len(set(self.allowed_strings)) != len(self.allowed_strings):
                raise RecordError(FailureCode.PARAMETER_INVALID, "duplicate allowed string")
        else:
            if self.allowed_strings:
                raise RecordError(
                    FailureCode.PARAMETER_INVALID, "allowed_strings only valid for string kind"
                )
        if self.kind is ValueKind.INTEGER:
            require_int(
                self.minimum, "parameter_spec.minimum", minimum=-MAX_PARAMETER_INT, maximum=MAX_PARAMETER_INT
            )
            require_int(
                self.maximum, "parameter_spec.maximum", minimum=-MAX_PARAMETER_INT, maximum=MAX_PARAMETER_INT
            )
            if self.minimum > self.maximum:
                raise RecordError(FailureCode.PARAMETER_INVALID, "minimum exceeds maximum")

    def accepts(self, value: TypedValue) -> bool:
        if value.kind is not self.kind:
            return False
        match self.kind:
            case ValueKind.STRING:
                return value.value in self.allowed_strings
            case ValueKind.INTEGER:
                return isinstance(value.value, int) and self.minimum <= value.value <= self.maximum
            case ValueKind.BOOLEAN:
                return isinstance(value.value, bool)
        return False

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("allowed_strings", self.allowed_strings),
                ("kind", self.KIND),
                ("maximum", self.maximum),
                ("minimum", self.minimum),
                ("name", self.name),
                ("required", self.required),
                ("value_kind", str(self.kind)),
            )
        )


@dataclass(frozen=True, slots=True)
class RegistryTemplate(_Record):
    """A registry-owned template identity.

    The registry (not the caller, and not the model) owns the executable
    handle. This record carries only an opaque fingerprint of that handle: no
    command, module, SQL, path, image or expression is representable here.
    """

    KIND: ClassVar[str] = "registry_template"

    template_id: str
    template_version: str
    handle_fingerprint: str
    parameter_specs: tuple[ParameterSpec, ...]

    def __post_init__(self) -> None:
        require_match(self.template_id, NAME_RE, "template_id")
        require_match(self.template_version, VERSION_RE, "template_version")
        require_digest(self.handle_fingerprint, "handle_fingerprint")
        require_tuple(self.parameter_specs, "parameter_specs", max_length=MAX_PARAMETERS)
        names = [spec.name for spec in self.parameter_specs]
        for spec in self.parameter_specs:
            if not isinstance(spec, ParameterSpec):
                raise RecordError(FailureCode.INVALID_TYPE, "parameter_specs must hold ParameterSpec")
        if len(set(names)) != len(names):
            raise RecordError(FailureCode.PARAMETER_INVALID, "duplicate parameter spec name")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("handle_fingerprint", self.handle_fingerprint),
                ("kind", self.KIND),
                ("parameter_specs", tuple(spec.canonical for spec in self.parameter_specs)),
                ("template_id", self.template_id),
                ("template_version", self.template_version),
            )
        )

    @property
    def template_digest(self) -> str:
        return self.digest

    def spec_for(self, name: str) -> ParameterSpec | None:
        for spec in self.parameter_specs:
            if spec.name == name:
                return spec
        return None


# ---------------------------------------------------------------------------
# Proposal + pre-approval records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRequest(_Record):
    """The immutable entry point for a run."""

    KIND: ClassVar[str] = "run_request"

    tenant_id: str
    run_id: str
    source_digest: str
    payload: CanonicalMap

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        if not isinstance(self.payload, CanonicalMap):
            raise RecordError(FailureCode.INVALID_TYPE, "payload must be a CanonicalMap")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("kind", self.KIND),
                ("payload", self.payload),
                ("run_id", self.run_id),
                ("source_digest", self.source_digest),
                ("tenant_id", self.tenant_id),
            )
        )

    @property
    def request_digest(self) -> str:
        return self.digest


@dataclass(frozen=True, slots=True)
class ValidatedProposal(_Record):
    """Prisma-validated proposal. Data only: no executable content."""

    KIND: ClassVar[str] = "validated_proposal"

    tenant_id: str
    run_id: str
    source_digest: str
    template_id: str
    template_version: str
    parameters: tuple[ParameterBinding, ...]
    summary: str
    payload_digest: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        require_match(self.template_id, NAME_RE, "template_id")
        require_match(self.template_version, VERSION_RE, "template_version")
        require_tuple(self.parameters, "parameters", max_length=MAX_PARAMETERS)
        names = [binding.name for binding in self.parameters]
        for binding in self.parameters:
            if not isinstance(binding, ParameterBinding):
                raise RecordError(FailureCode.INVALID_TYPE, "parameters must hold ParameterBinding")
        if len(set(names)) != len(names):
            raise RecordError(FailureCode.PARAMETER_INVALID, "duplicate parameter name")
        if names != sorted(names):
            object.__setattr__(
                self, "parameters", tuple(sorted(self.parameters, key=lambda b: b.name))
            )
        require_safe_text(self.summary, "summary", max_length=MAX_SUMMARY_LENGTH)
        require_digest(self.payload_digest, "payload_digest")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("kind", self.KIND),
                ("parameters", tuple(binding.canonical for binding in self.parameters)),
                ("payload_digest", self.payload_digest),
                ("run_id", self.run_id),
                ("source_digest", self.source_digest),
                ("summary", self.summary),
                ("template_id", self.template_id),
                ("template_version", self.template_version),
                ("tenant_id", self.tenant_id),
            )
        )

    @property
    def proposal_digest(self) -> str:
        return self.digest

    @classmethod
    def from_canonical(
        cls, source: CanonicalMap, *, context: str = "validated_proposal"
    ) -> "ValidatedProposal":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        parameters = tuple(
            ParameterBinding.from_canonical(item, context=f"{context}.parameters")
            for item in reader.submaps("parameters")
        )
        record = cls(
            tenant_id=reader.text("tenant_id"),
            run_id=reader.text("run_id"),
            source_digest=reader.text("source_digest"),
            template_id=reader.text("template_id"),
            template_version=reader.text("template_version"),
            parameters=parameters,
            summary=reader.text("summary"),
            payload_digest=reader.text("payload_digest"),
        )
        reader.done()
        return record


@dataclass(frozen=True, slots=True)
class RepairRequest(_Record):
    """Bounded, closed request handed to the model repair adapter."""

    KIND: ClassVar[str] = "repair_request"

    tenant_id: str
    run_id: str
    source_digest: str
    attempt: int
    payload: CanonicalMap
    failure_code: FailureCode
    failure_detail: str
    idempotency_key: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        require_int(self.attempt, "attempt", minimum=1, maximum=MAX_REPAIRS)
        if not isinstance(self.payload, CanonicalMap):
            raise RecordError(FailureCode.INVALID_TYPE, "payload must be a CanonicalMap")
        if not isinstance(self.failure_code, FailureCode):
            raise RecordError(FailureCode.INVALID_TYPE, "failure_code must be a FailureCode")
        if len(self.failure_detail) > MAX_TEXT_LENGTH:
            raise RecordError(FailureCode.INVALID_COUNT, "failure_detail too long")
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("attempt", self.attempt),
                ("failure_code", str(self.failure_code)),
                ("failure_detail", self.failure_detail),
                ("idempotency_key", self.idempotency_key),
                ("kind", self.KIND),
                ("payload", self.payload),
                ("run_id", self.run_id),
                ("source_digest", self.source_digest),
                ("tenant_id", self.tenant_id),
            )
        )


@dataclass(frozen=True, slots=True)
class PolicyConfig(_Record):
    """Injected, immutable deterministic policy configuration."""

    KIND: ClassVar[str] = "policy_config"

    policy_id: str
    policy_version: str
    allowed_tenants: tuple[str, ...]
    allowed_templates: tuple[tuple[str, str], ...]
    obligations: tuple[str, ...] = ()
    max_parameters: int = MAX_PARAMETERS

    def __post_init__(self) -> None:
        require_match(self.policy_id, NAME_RE, "policy_id")
        require_match(self.policy_version, VERSION_RE, "policy_version")
        require_tuple(self.allowed_tenants, "allowed_tenants", max_length=32)
        for tenant in self.allowed_tenants:
            require_match(tenant, TENANT_RE, "allowed_tenants[]")
        require_tuple(self.allowed_templates, "allowed_templates", max_length=32)
        for entry in self.allowed_templates:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise RecordError(FailureCode.INVALID_TYPE, "allowed_templates entries are pairs")
            require_match(entry[0], NAME_RE, "allowed_templates[].template_id")
            require_match(entry[1], VERSION_RE, "allowed_templates[].template_version")
        require_tuple(self.obligations, "obligations", max_length=16)
        for obligation in self.obligations:
            require_match(obligation, NAME_RE, "obligations[]")
        require_int(self.max_parameters, "max_parameters", minimum=0, maximum=MAX_PARAMETERS)

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("allowed_templates", tuple(tuple(entry) for entry in self.allowed_templates)),
                ("allowed_tenants", self.allowed_tenants),
                ("kind", self.KIND),
                ("max_parameters", self.max_parameters),
                ("obligations", self.obligations),
                ("policy_id", self.policy_id),
                ("policy_version", self.policy_version),
            )
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision(_Record):
    """Deterministic policy result, fully bound to its inputs."""

    KIND: ClassVar[str] = "policy_decision"

    tenant_id: str
    run_id: str
    source_digest: str
    proposal_digest: str
    template_id: str
    template_version: str
    template_digest: str
    parameters: tuple[ParameterBinding, ...]
    policy_id: str
    policy_version: str
    policy_config_digest: str
    obligations: tuple[str, ...]
    allowed: bool

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        require_digest(self.proposal_digest, "proposal_digest")
        require_match(self.template_id, NAME_RE, "template_id")
        require_match(self.template_version, VERSION_RE, "template_version")
        require_digest(self.template_digest, "template_digest")
        require_tuple(self.parameters, "parameters", max_length=MAX_PARAMETERS)
        require_match(self.policy_id, NAME_RE, "policy_id")
        require_match(self.policy_version, VERSION_RE, "policy_version")
        require_digest(self.policy_config_digest, "policy_config_digest")
        require_tuple(self.obligations, "obligations", max_length=16)
        require_bool(self.allowed, "allowed")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("allowed", self.allowed),
                ("kind", self.KIND),
                ("obligations", self.obligations),
                ("parameters", tuple(binding.canonical for binding in self.parameters)),
                ("policy_config_digest", self.policy_config_digest),
                ("policy_id", self.policy_id),
                ("policy_version", self.policy_version),
                ("proposal_digest", self.proposal_digest),
                ("run_id", self.run_id),
                ("source_digest", self.source_digest),
                ("template_digest", self.template_digest),
                ("template_id", self.template_id),
                ("template_version", self.template_version),
                ("tenant_id", self.tenant_id),
            )
        )


@dataclass(frozen=True, slots=True)
class ValeVerdict(_Record):
    """Independent verification. Verifies only; never repairs or widens."""

    KIND: ClassVar[str] = "vale_verdict"

    tenant_id: str
    run_id: str
    source_digest: str
    proposal_digest: str
    policy_digest: str
    template_digest: str
    obligations: tuple[str, ...]
    verified: bool

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        require_digest(self.proposal_digest, "proposal_digest")
        require_digest(self.policy_digest, "policy_digest")
        require_digest(self.template_digest, "template_digest")
        require_tuple(self.obligations, "obligations", max_length=16)
        require_bool(self.verified, "verified")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("kind", self.KIND),
                ("obligations", self.obligations),
                ("policy_digest", self.policy_digest),
                ("proposal_digest", self.proposal_digest),
                ("run_id", self.run_id),
                ("source_digest", self.source_digest),
                ("template_digest", self.template_digest),
                ("tenant_id", self.tenant_id),
                ("verified", self.verified),
            )
        )


# ---------------------------------------------------------------------------
# Approval boundary records (not model nodes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApprovalQuery(_Record):
    """What the runtime asks the authenticated approval authority for."""

    KIND: ClassVar[str] = "approval_query"

    tenant_id: str
    run_id: str
    source_digest: str
    stage: Stage
    subject_digest: str
    predecessor_digest: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        if not isinstance(self.stage, Stage):
            raise RecordError(FailureCode.INVALID_TYPE, "stage must be a Stage")
        require_digest(self.subject_digest, "subject_digest")
        require_digest(self.predecessor_digest, "predecessor_digest")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("kind", self.KIND),
                ("predecessor_digest", self.predecessor_digest),
                ("run_id", self.run_id),
                ("source_digest", self.source_digest),
                ("stage", str(self.stage)),
                ("subject_digest", self.subject_digest),
                ("tenant_id", self.tenant_id),
            )
        )


@dataclass(frozen=True, slots=True)
class ApprovalRecord(_Record):
    """An approval decision issued by the authenticated approval authority.

    This record can only originate from the injected approval authority; the
    runtime never accepts one from generic resume input or model output.
    """

    KIND: ClassVar[str] = "approval_record"

    tenant_id: str
    run_id: str
    source_digest: str
    stage: Stage
    subject_digest: str
    predecessor_digest: str
    decision: Decision
    approver_id: str
    idempotency_key: str
    authority_id: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        if not isinstance(self.stage, Stage):
            raise RecordError(FailureCode.INVALID_TYPE, "stage must be a Stage")
        if not isinstance(self.decision, Decision):
            raise RecordError(FailureCode.INVALID_TYPE, "decision must be a Decision")
        require_digest(self.subject_digest, "subject_digest")
        require_digest(self.predecessor_digest, "predecessor_digest")
        require_match(self.approver_id, PRINCIPAL_RE, "approver_id")
        require_match(self.authority_id, PRINCIPAL_RE, "authority_id")
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("approver_id", self.approver_id),
                ("authority_id", self.authority_id),
                ("decision", str(self.decision)),
                ("idempotency_key", self.idempotency_key),
                ("kind", self.KIND),
                ("predecessor_digest", self.predecessor_digest),
                ("run_id", self.run_id),
                ("source_digest", self.source_digest),
                ("stage", str(self.stage)),
                ("subject_digest", self.subject_digest),
                ("tenant_id", self.tenant_id),
            )
        )

    @classmethod
    def from_canonical(
        cls, source: CanonicalMap, *, context: str = "approval_record"
    ) -> "ApprovalRecord":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        record = cls(
            tenant_id=reader.text("tenant_id"),
            run_id=reader.text("run_id"),
            source_digest=reader.text("source_digest"),
            stage=Stage(reader.enum("stage", Stage)),
            subject_digest=reader.text("subject_digest"),
            predecessor_digest=reader.text("predecessor_digest"),
            decision=Decision(reader.enum("decision", Decision)),
            approver_id=reader.text("approver_id"),
            idempotency_key=reader.text("idempotency_key"),
            authority_id=reader.text("authority_id"),
        )
        reader.done()
        return record


# ---------------------------------------------------------------------------
# Execution bundle + post-approval records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionBundle(_Record):
    """Everything execution is allowed to know, assembled pre-production."""

    KIND: ClassVar[str] = "execution_bundle"

    tenant_id: str
    run_id: str
    source_digest: str
    proposal_digest: str
    policy_digest: str
    vale_digest: str
    simulation_approval_digest: str
    template_id: str
    template_version: str
    template_digest: str
    parameters: tuple[ParameterBinding, ...]

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        for name in (
            "source_digest",
            "proposal_digest",
            "policy_digest",
            "vale_digest",
            "simulation_approval_digest",
            "template_digest",
        ):
            require_digest(getattr(self, name), name)
        require_match(self.template_id, NAME_RE, "template_id")
        require_match(self.template_version, VERSION_RE, "template_version")
        require_tuple(self.parameters, "parameters", max_length=MAX_PARAMETERS)

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("kind", self.KIND),
                ("parameters", tuple(binding.canonical for binding in self.parameters)),
                ("policy_digest", self.policy_digest),
                ("proposal_digest", self.proposal_digest),
                ("run_id", self.run_id),
                ("simulation_approval_digest", self.simulation_approval_digest),
                ("source_digest", self.source_digest),
                ("template_digest", self.template_digest),
                ("template_id", self.template_id),
                ("template_version", self.template_version),
                ("tenant_id", self.tenant_id),
                ("vale_digest", self.vale_digest),
            )
        )

    @property
    def bundle_digest(self) -> str:
        return self.digest

    @classmethod
    def from_canonical(
        cls, source: CanonicalMap, *, context: str = "execution_bundle"
    ) -> "ExecutionBundle":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        parameters = tuple(
            ParameterBinding.from_canonical(item, context=f"{context}.parameters")
            for item in reader.submaps("parameters")
        )
        record = cls(
            tenant_id=reader.text("tenant_id"),
            run_id=reader.text("run_id"),
            source_digest=reader.text("source_digest"),
            proposal_digest=reader.text("proposal_digest"),
            policy_digest=reader.text("policy_digest"),
            vale_digest=reader.text("vale_digest"),
            simulation_approval_digest=reader.text("simulation_approval_digest"),
            template_id=reader.text("template_id"),
            template_version=reader.text("template_version"),
            template_digest=reader.text("template_digest"),
            parameters=parameters,
        )
        reader.done()
        return record


@dataclass(frozen=True, slots=True)
class SealedBundle(_Record):
    """The execution bundle sealed by the production approval."""

    KIND: ClassVar[str] = "sealed_bundle"

    bundle: ExecutionBundle
    production_approval_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.bundle, ExecutionBundle):
            raise RecordError(FailureCode.INVALID_TYPE, "bundle must be an ExecutionBundle")
        require_digest(self.production_approval_digest, "production_approval_digest")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("bundle", self.bundle.canonical),
                ("bundle_digest", self.bundle.bundle_digest),
                ("kind", self.KIND),
                ("production_approval_digest", self.production_approval_digest),
            )
        )

    @property
    def seal_digest(self) -> str:
        return self.digest

    @property
    def tenant_id(self) -> str:
        return self.bundle.tenant_id

    @property
    def run_id(self) -> str:
        return self.bundle.run_id

    @property
    def source_digest(self) -> str:
        return self.bundle.source_digest

    @classmethod
    def from_canonical(
        cls, source: CanonicalMap, *, context: str = "sealed_bundle"
    ) -> "SealedBundle":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        bundle = ExecutionBundle.from_canonical(
            reader.submap("bundle"), context=f"{context}.bundle"
        )
        expected_bundle_digest = reader.text("bundle_digest")
        record = cls(
            bundle=bundle,
            production_approval_digest=reader.text("production_approval_digest"),
        )
        reader.done()
        if bundle.bundle_digest != expected_bundle_digest:
            raise DurabilityError(
                FailureCode.CHAIN_CORRUPTION,
                f"{context}: execution bundle digest mismatch",
            )
        return record


@dataclass(frozen=True, slots=True)
class DispatchRequest(_Record):
    """The only thing Flow is ever handed. No strings-as-targets exist here."""

    KIND: ClassVar[str] = "dispatch_request"

    sealed: SealedBundle
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.sealed, SealedBundle):
            raise RecordError(FailureCode.INVALID_TYPE, "sealed must be a SealedBundle")
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("idempotency_key", self.idempotency_key),
                ("kind", self.KIND),
                ("seal_digest", self.sealed.seal_digest),
                ("sealed", self.sealed.canonical),
            )
        )

    @property
    def template_id(self) -> str:
        return self.sealed.bundle.template_id

    @property
    def template_version(self) -> str:
        return self.sealed.bundle.template_version

    @property
    def parameters(self) -> tuple[ParameterBinding, ...]:
        return self.sealed.bundle.parameters


@dataclass(frozen=True, slots=True)
class DispatchReceipt(_Record):
    """Flow's receipt for one dispatched template execution."""

    KIND: ClassVar[str] = "dispatch_receipt"

    tenant_id: str
    run_id: str
    seal_digest: str
    bundle_digest: str
    template_id: str
    template_version: str
    template_digest: str
    dispatch_id: str
    effect_digest: str
    idempotency_key: str
    dispatcher_id: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        for name in ("seal_digest", "bundle_digest", "template_digest", "effect_digest"):
            require_digest(getattr(self, name), name)
        require_match(self.template_id, NAME_RE, "template_id")
        require_match(self.template_version, VERSION_RE, "template_version")
        require_match(self.dispatch_id, REFERENCE_RE, "dispatch_id")
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")
        require_match(self.dispatcher_id, PRINCIPAL_RE, "dispatcher_id")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("bundle_digest", self.bundle_digest),
                ("dispatch_id", self.dispatch_id),
                ("dispatcher_id", self.dispatcher_id),
                ("effect_digest", self.effect_digest),
                ("idempotency_key", self.idempotency_key),
                ("kind", self.KIND),
                ("run_id", self.run_id),
                ("seal_digest", self.seal_digest),
                ("template_digest", self.template_digest),
                ("template_id", self.template_id),
                ("template_version", self.template_version),
                ("tenant_id", self.tenant_id),
            )
        )

    @classmethod
    def from_canonical(
        cls, source: CanonicalMap, *, context: str = "dispatch_receipt"
    ) -> "DispatchReceipt":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        record = cls(
            tenant_id=reader.text("tenant_id"),
            run_id=reader.text("run_id"),
            seal_digest=reader.text("seal_digest"),
            bundle_digest=reader.text("bundle_digest"),
            template_id=reader.text("template_id"),
            template_version=reader.text("template_version"),
            template_digest=reader.text("template_digest"),
            dispatch_id=reader.text("dispatch_id"),
            effect_digest=reader.text("effect_digest"),
            idempotency_key=reader.text("idempotency_key"),
            dispatcher_id=reader.text("dispatcher_id"),
        )
        reader.done()
        return record


@dataclass(frozen=True, slots=True)
class ReconciliationQuery(_Record):
    """Ledger reads are bound to the receipt and the sealed expectations."""

    KIND: ClassVar[str] = "reconciliation_query"

    tenant_id: str
    run_id: str
    seal_digest: str
    bundle_digest: str
    dispatch_id: str
    effect_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        for name in ("seal_digest", "bundle_digest", "effect_digest"):
            require_digest(getattr(self, name), name)
        require_match(self.dispatch_id, REFERENCE_RE, "dispatch_id")
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("bundle_digest", self.bundle_digest),
                ("dispatch_id", self.dispatch_id),
                ("effect_digest", self.effect_digest),
                ("idempotency_key", self.idempotency_key),
                ("kind", self.KIND),
                ("run_id", self.run_id),
                ("seal_digest", self.seal_digest),
                ("tenant_id", self.tenant_id),
            )
        )


@dataclass(frozen=True, slots=True)
class ReconciliationReport(_Record):
    """Ledger's answer for one dispatched effect."""

    KIND: ClassVar[str] = "reconciliation_report"

    tenant_id: str
    run_id: str
    seal_digest: str
    bundle_digest: str
    dispatch_id: str
    effect_digest: str
    entry_digest: str
    ledger_ref: str
    reconciled: bool
    idempotency_key: str
    reader_id: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        for name in ("seal_digest", "bundle_digest", "effect_digest", "entry_digest"):
            require_digest(getattr(self, name), name)
        require_match(self.dispatch_id, REFERENCE_RE, "dispatch_id")
        require_match(self.ledger_ref, REFERENCE_RE, "ledger_ref")
        require_bool(self.reconciled, "reconciled")
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")
        require_match(self.reader_id, PRINCIPAL_RE, "reader_id")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("bundle_digest", self.bundle_digest),
                ("dispatch_id", self.dispatch_id),
                ("effect_digest", self.effect_digest),
                ("entry_digest", self.entry_digest),
                ("idempotency_key", self.idempotency_key),
                ("kind", self.KIND),
                ("ledger_ref", self.ledger_ref),
                ("reader_id", self.reader_id),
                ("reconciled", self.reconciled),
                ("run_id", self.run_id),
                ("seal_digest", self.seal_digest),
                ("tenant_id", self.tenant_id),
            )
        )

    @classmethod
    def from_canonical(
        cls, source: CanonicalMap, *, context: str = "reconciliation_report"
    ) -> "ReconciliationReport":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        record = cls(
            tenant_id=reader.text("tenant_id"),
            run_id=reader.text("run_id"),
            seal_digest=reader.text("seal_digest"),
            bundle_digest=reader.text("bundle_digest"),
            dispatch_id=reader.text("dispatch_id"),
            effect_digest=reader.text("effect_digest"),
            entry_digest=reader.text("entry_digest"),
            ledger_ref=reader.text("ledger_ref"),
            reconciled=reader.flag("reconciled"),
            idempotency_key=reader.text("idempotency_key"),
            reader_id=reader.text("reader_id"),
        )
        reader.done()
        return record


@dataclass(frozen=True, slots=True)
class CertificationRequest(_Record):
    """Forge sees only the seal, the reconciliation and the chain."""

    KIND: ClassVar[str] = "certification_request"

    tenant_id: str
    run_id: str
    seal_digest: str
    reconciliation_digest: str
    chain_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        for name in ("seal_digest", "reconciliation_digest", "chain_digest"):
            require_digest(getattr(self, name), name)
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("chain_digest", self.chain_digest),
                ("idempotency_key", self.idempotency_key),
                ("kind", self.KIND),
                ("reconciliation_digest", self.reconciliation_digest),
                ("run_id", self.run_id),
                ("seal_digest", self.seal_digest),
                ("tenant_id", self.tenant_id),
            )
        )


@dataclass(frozen=True, slots=True)
class Certificate(_Record):
    """Forge's signed certificate and release reference."""

    KIND: ClassVar[str] = "certificate"

    tenant_id: str
    run_id: str
    seal_digest: str
    reconciliation_digest: str
    chain_digest: str
    signer_id: str
    signature: str
    released: bool
    release_ref: str
    idempotency_key: str

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        for name in ("seal_digest", "reconciliation_digest", "chain_digest"):
            require_digest(getattr(self, name), name)
        require_match(self.signer_id, PRINCIPAL_RE, "signer_id")
        require_match(self.signature, SIGNATURE_RE, "signature")
        require_bool(self.released, "released")
        require_match(self.release_ref, REFERENCE_RE, "release_ref")
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("chain_digest", self.chain_digest),
                ("idempotency_key", self.idempotency_key),
                ("kind", self.KIND),
                ("reconciliation_digest", self.reconciliation_digest),
                ("release_ref", self.release_ref),
                ("released", self.released),
                ("run_id", self.run_id),
                ("seal_digest", self.seal_digest),
                ("signature", self.signature),
                ("signer_id", self.signer_id),
                ("tenant_id", self.tenant_id),
            )
        )

    @classmethod
    def from_canonical(cls, source: CanonicalMap, *, context: str = "certificate") -> "Certificate":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        record = cls(
            tenant_id=reader.text("tenant_id"),
            run_id=reader.text("run_id"),
            seal_digest=reader.text("seal_digest"),
            reconciliation_digest=reader.text("reconciliation_digest"),
            chain_digest=reader.text("chain_digest"),
            signer_id=reader.text("signer_id"),
            signature=reader.text("signature"),
            released=reader.flag("released"),
            release_ref=reader.text("release_ref"),
            idempotency_key=reader.text("idempotency_key"),
        )
        reader.done()
        return record


# ---------------------------------------------------------------------------
# Durable audit records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NodeRecord(_Record):
    """One durable audit record for one node attempt.

    Binds tenant/run/source, node name, sequence, predecessor digest, input
    digest, output-or-error digest, idempotency key, status and the model call
    delta charged by this record.
    """

    KIND: ClassVar[str] = "node_record"

    tenant_id: str
    run_id: str
    source_digest: str
    node: NodeName
    sequence: int
    attempt: int
    predecessor_digest: str
    input_digest: str
    output_digest: str | None
    error_digest: str | None
    idempotency_key: str
    status: NodeStatus
    model_call_delta: int

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        if not isinstance(self.node, NodeName):
            raise RecordError(FailureCode.INVALID_TYPE, "node must be a NodeName")
        if not isinstance(self.status, NodeStatus):
            raise RecordError(FailureCode.INVALID_TYPE, "status must be a NodeStatus")
        require_int(self.sequence, "sequence", minimum=0, maximum=MAX_TRACE_RECORDS)
        require_int(self.attempt, "attempt", minimum=0, maximum=MAX_REPAIRS + 1)
        require_digest(self.predecessor_digest, "predecessor_digest")
        require_digest(self.input_digest, "input_digest")
        require_optional_digest(self.output_digest, "output_digest")
        require_optional_digest(self.error_digest, "error_digest")
        require_match(self.idempotency_key, IDEMPOTENCY_KEY_RE, "idempotency_key")
        require_int(self.model_call_delta, "model_call_delta", minimum=0, maximum=1)
        if self.model_call_delta and self.node not in MODEL_NODES:
            raise RecordError(
                FailureCode.BINDING_MISMATCH, "only model nodes may charge a model call"
            )
        match self.status:
            case NodeStatus.STARTED:
                if self.output_digest is not None or self.error_digest is not None:
                    raise RecordError(FailureCode.BINDING_MISMATCH, "intent record carries no result")
            case NodeStatus.SUCCEEDED:
                if self.output_digest is None or self.error_digest is not None:
                    raise RecordError(FailureCode.BINDING_MISMATCH, "success requires output digest")
            case NodeStatus.FAILED:
                if self.error_digest is None or self.output_digest is not None:
                    raise RecordError(FailureCode.BINDING_MISMATCH, "failure requires error digest")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("attempt", self.attempt),
                ("error_digest", self.error_digest),
                ("idempotency_key", self.idempotency_key),
                ("input_digest", self.input_digest),
                ("kind", self.KIND),
                ("model_call_delta", self.model_call_delta),
                ("node", str(self.node)),
                ("output_digest", self.output_digest),
                ("predecessor_digest", self.predecessor_digest),
                ("run_id", self.run_id),
                ("sequence", self.sequence),
                ("source_digest", self.source_digest),
                ("status", str(self.status)),
                ("tenant_id", self.tenant_id),
            )
        )

    @classmethod
    def from_canonical(cls, source: CanonicalMap, *, context: str = "node_record") -> "NodeRecord":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        record = cls(
            tenant_id=reader.text("tenant_id"),
            run_id=reader.text("run_id"),
            source_digest=reader.text("source_digest"),
            node=NodeName(reader.enum("node", NodeName)),
            sequence=reader.integer("sequence"),
            attempt=reader.integer("attempt"),
            predecessor_digest=reader.text("predecessor_digest"),
            input_digest=reader.text("input_digest"),
            output_digest=reader.optional_text("output_digest"),
            error_digest=reader.optional_text("error_digest"),
            idempotency_key=reader.text("idempotency_key"),
            status=NodeStatus(reader.enum("status", NodeStatus)),
            model_call_delta=reader.integer("model_call_delta"),
        )
        reader.done()
        return record


#: Keys permitted inside the durable checkpoint state map.
CHECKPOINT_STATE_KEYS: Final[frozenset[str]] = frozenset(
    {"proposal", "payload", "sealed_bundle", "receipt", "reconciliation", "certificate"}
)


@dataclass(frozen=True, slots=True)
class RunCheckpoint(_Record):
    """Durable resumable state. The store, not the caller, is the authority.

    The checkpoint is also the *proof carrier* for the production boundary:

    * ``phase`` is monotonic (see :func:`phase_index`); it never moves back.
    * At :data:`SEALING_PHASE` the checkpoint records ``seal_digest`` and
      freezes ``model_calls`` into ``model_calls_at_seal``.
    * ``post_seal_model_calls`` is structurally pinned to
      :data:`POST_PRODUCTION_MODEL_CALLS` (0). A checkpoint that claims a
      post-production model call cannot be constructed at all.
    """

    KIND: ClassVar[str] = "run_checkpoint"

    tenant_id: str
    run_id: str
    source_digest: str
    request_digest: str
    plan_digest: str
    sequence: int
    chain_digest: str
    state: CanonicalMap
    phase: RunPhase = RunPhase.PLANNED
    model_calls: int = 0
    model_calls_at_seal: int | None = None
    post_seal_model_calls: int = POST_PRODUCTION_MODEL_CALLS
    seal_digest: str | None = None

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        require_digest(self.source_digest, "source_digest")
        require_digest(self.request_digest, "request_digest")
        require_digest(self.plan_digest, "plan_digest")
        require_int(self.sequence, "sequence", minimum=0, maximum=MAX_TRACE_RECORDS)
        require_digest(self.chain_digest, "chain_digest")
        if not isinstance(self.state, CanonicalMap):
            raise RecordError(FailureCode.INVALID_TYPE, "state must be a CanonicalMap")
        unknown = tuple(key for key in self.state.keys() if key not in CHECKPOINT_STATE_KEYS)
        if unknown:
            raise RecordError(FailureCode.UNKNOWN_FIELD, f"unknown checkpoint keys {unknown!r}")
        if not isinstance(self.phase, RunPhase):
            raise RecordError(FailureCode.INVALID_TYPE, "phase must be a RunPhase")
        require_int(self.model_calls, "model_calls", minimum=0, maximum=MAX_MODEL_CALLS)
        if self.model_calls_at_seal is not None:
            require_int(
                self.model_calls_at_seal, "model_calls_at_seal", minimum=0, maximum=MAX_MODEL_CALLS
            )
        if self.post_seal_model_calls != POST_PRODUCTION_MODEL_CALLS:
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL,
                "checkpoint recorded a model call after the production boundary",
            )
        require_optional_digest(self.seal_digest, "seal_digest")
        if self.sealed:
            if self.seal_digest is None:
                raise RecordError(
                    FailureCode.BINDING_MISMATCH, "sealed checkpoint requires a seal digest"
                )
            if self.model_calls_at_seal is None:
                raise RecordError(
                    FailureCode.BINDING_MISMATCH, "sealed checkpoint must freeze the model-call count"
                )
            if self.model_calls != self.model_calls_at_seal:
                raise BudgetError(
                    FailureCode.POST_APPROVAL_MODEL_CALL,
                    "model-call total moved after the production boundary",
                )
        elif self.seal_digest is not None or self.model_calls_at_seal is not None:
            raise RecordError(
                FailureCode.BINDING_MISMATCH, "unsealed checkpoint must not carry seal state"
            )

    @property
    def sealed(self) -> bool:
        """True once the production approval sealed this run."""
        return is_sealed_phase(self.phase)

    @property
    def proves_post_production_model_free(self) -> bool:
        """The checkpoint's own proof that no model ran after the boundary."""
        return (
            self.sealed
            and self.post_seal_model_calls == POST_PRODUCTION_MODEL_CALLS
            and self.model_calls_at_seal == self.model_calls
        )

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("chain_digest", self.chain_digest),
                ("kind", self.KIND),
                ("model_calls", self.model_calls),
                ("model_calls_at_seal", self.model_calls_at_seal),
                ("phase", str(self.phase)),
                ("plan_digest", self.plan_digest),
                ("post_seal_model_calls", self.post_seal_model_calls),
                ("request_digest", self.request_digest),
                ("run_id", self.run_id),
                ("seal_digest", self.seal_digest),
                ("sequence", self.sequence),
                ("source_digest", self.source_digest),
                ("state", self.state),
                ("tenant_id", self.tenant_id),
            )
        )

    def advanced(
        self,
        *,
        phase: RunPhase,
        chain_digest: str,
        sequence: int,
        model_calls: int,
        state_key: str | None = None,
        state_value: CanonicalValue = None,
        seal_digest: str | None = None,
    ) -> "RunCheckpoint":
        """Return the next checkpoint, refusing every backwards transition."""
        if phase_index(phase) < phase_index(self.phase):
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, "checkpoint phase cannot move backwards"
            )
        if sequence < self.sequence:
            raise DurabilityError(
                FailureCode.STATE_CORRUPTION, "checkpoint sequence cannot move backwards"
            )
        if state_key is not None and state_key not in CHECKPOINT_STATE_KEYS:
            raise RecordError(FailureCode.UNKNOWN_FIELD, f"unknown checkpoint key {state_key!r}")
        if self.sealed:
            if seal_digest is not None and seal_digest != self.seal_digest:
                raise DurabilityError(
                    FailureCode.STATE_CORRUPTION, "a sealed checkpoint cannot be resealed"
                )
            if model_calls != self.model_calls:
                raise BudgetError(
                    FailureCode.POST_APPROVAL_MODEL_CALL,
                    "model-call total cannot change after the seal",
                )
        state = self.state if state_key is None else self.state.updated({state_key: state_value})
        next_seal = self.seal_digest if self.seal_digest is not None else seal_digest
        at_seal = self.model_calls_at_seal
        if at_seal is None and is_sealed_phase(phase):
            at_seal = model_calls
        return replace(
            self,
            phase=phase,
            chain_digest=chain_digest,
            sequence=sequence,
            state=state,
            model_calls=model_calls,
            model_calls_at_seal=at_seal,
            seal_digest=next_seal,
        )


@dataclass(frozen=True, slots=True)
class RunResult(_Record):
    """The immutable, replay-stable outcome of a completed run."""

    KIND: ClassVar[str] = "run_result"

    tenant_id: str
    run_id: str
    source_digest: str
    request_digest: str
    proposal_digest: str
    seal_digest: str
    chain_digest: str
    certificate: Certificate
    approvals: tuple[ApprovalRecord, ...]
    trace: tuple[NodeRecord, ...]
    model_calls_used: int
    repair_attempts: int

    def __post_init__(self) -> None:
        require_match(self.tenant_id, TENANT_RE, "tenant_id")
        require_match(self.run_id, RUN_ID_RE, "run_id")
        for name in ("source_digest", "request_digest", "proposal_digest", "seal_digest", "chain_digest"):
            require_digest(getattr(self, name), name)
        if not isinstance(self.certificate, Certificate):
            raise RecordError(FailureCode.INVALID_TYPE, "certificate must be a Certificate")
        require_tuple(self.approvals, "approvals", max_length=8)
        require_tuple(self.trace, "trace", max_length=MAX_TRACE_RECORDS)
        require_int(self.model_calls_used, "model_calls_used", minimum=0, maximum=MAX_MODEL_CALLS)
        require_int(self.repair_attempts, "repair_attempts", minimum=0, maximum=MAX_REPAIRS)

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("approvals", tuple(item.canonical for item in self.approvals)),
                ("certificate", self.certificate.canonical),
                ("chain_digest", self.chain_digest),
                ("kind", self.KIND),
                ("model_calls_used", self.model_calls_used),
                ("proposal_digest", self.proposal_digest),
                ("repair_attempts", self.repair_attempts),
                ("request_digest", self.request_digest),
                ("run_id", self.run_id),
                ("seal_digest", self.seal_digest),
                ("source_digest", self.source_digest),
                ("tenant_id", self.tenant_id),
                ("trace", tuple(item.canonical for item in self.trace)),
            )
        )

    @property
    def completed_nodes(self) -> tuple[NodeName, ...]:
        """Node names of successful attempts, in durable order."""
        return tuple(
            record.node for record in self.trace if record.status is NodeStatus.SUCCEEDED
        )

    @property
    def post_production_model_calls(self) -> int:
        """Model calls charged at or after production approval. Always 0."""
        post = False
        total = 0
        for record in self.trace:
            if record.node in SIDE_EFFECT_NODES:
                post = True
            if post:
                total += record.model_call_delta
        return total

    def records_for(self, node: NodeName) -> tuple[NodeRecord, ...]:
        return tuple(record for record in self.trace if record.node == node)

    @classmethod
    def from_canonical(cls, source: CanonicalMap, *, context: str = "run_result") -> "RunResult":
        reader = MapReader(source, context=context)
        reader.expect_kind(cls.KIND)
        approvals = tuple(
            ApprovalRecord.from_canonical(item, context=f"{context}.approvals")
            for item in reader.submaps("approvals")
        )
        trace = tuple(
            NodeRecord.from_canonical(item, context=f"{context}.trace")
            for item in reader.submaps("trace")
        )
        certificate = Certificate.from_canonical(
            reader.submap("certificate"), context=f"{context}.certificate"
        )
        record = cls(
            tenant_id=reader.text("tenant_id"),
            run_id=reader.text("run_id"),
            source_digest=reader.text("source_digest"),
            request_digest=reader.text("request_digest"),
            proposal_digest=reader.text("proposal_digest"),
            seal_digest=reader.text("seal_digest"),
            chain_digest=reader.text("chain_digest"),
            certificate=certificate,
            approvals=approvals,
            trace=trace,
            model_calls_used=reader.integer("model_calls_used"),
            repair_attempts=reader.integer("repair_attempts"),
        )
        reader.done()
        return record


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BudgetPolicy(_Record):
    """Bounded shape of a run. Values may only tighten the module ceilings."""

    KIND: ClassVar[str] = "budget_policy"

    max_repairs: int = MAX_REPAIRS
    max_model_calls: int = MAX_MODEL_CALLS
    post_production_model_calls: int = POST_PRODUCTION_MODEL_CALLS
    side_effect_concurrency: int = SIDE_EFFECT_CONCURRENCY
    max_depth: int = MAX_DEPTH

    def __post_init__(self) -> None:
        require_int(self.max_repairs, "max_repairs", minimum=0, maximum=MAX_REPAIRS)
        require_int(self.max_model_calls, "max_model_calls", minimum=0, maximum=MAX_MODEL_CALLS)
        if self.post_production_model_calls != POST_PRODUCTION_MODEL_CALLS:
            raise RecordError(
                FailureCode.POST_APPROVAL_MODEL_CALL,
                "post-production model budget is fixed at 0",
            )
        if self.side_effect_concurrency != SIDE_EFFECT_CONCURRENCY:
            raise RecordError(
                FailureCode.CONCURRENCY_VIOLATION, "side-effect concurrency is fixed at 1"
            )
        if self.max_depth != MAX_DEPTH:
            raise RecordError(FailureCode.DEPTH_EXCEEDED, "recursion depth is fixed at 0")

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("kind", self.KIND),
                ("max_depth", self.max_depth),
                ("max_model_calls", self.max_model_calls),
                ("max_repairs", self.max_repairs),
                ("post_production_model_calls", self.post_production_model_calls),
                ("side_effect_concurrency", self.side_effect_concurrency),
            )
        )


DEFAULT_BUDGET: Final[BudgetPolicy] = BudgetPolicy()


# ---------------------------------------------------------------------------
# The frozen plan: the only accepted first state
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrozenPlan(_Record):
    """The immutable plan a run starts from.

    The runtime accepts *this type only* as its entry state. A mapping, a
    dict-shaped "plan", a mutable object or a plan whose node list differs from
    :data:`NODE_PLAN` is refused at the boundary rather than coerced. Every
    field is itself frozen: the request, the policy configuration and the
    budget are all immutable records, and the payload is a
    :class:`CanonicalMap`, so the plan digest is stable for the life of the run.
    """

    KIND: ClassVar[str] = "frozen_plan"

    request: RunRequest
    policy_config: PolicyConfig
    budget: BudgetPolicy = DEFAULT_BUDGET
    node_plan: tuple[NodeName, ...] = NODE_PLAN

    def __post_init__(self) -> None:
        if not isinstance(self.request, RunRequest):
            raise RecordError(FailureCode.INVALID_TYPE, "plan.request must be a RunRequest")
        if not isinstance(self.policy_config, PolicyConfig):
            raise RecordError(FailureCode.INVALID_TYPE, "plan.policy_config must be a PolicyConfig")
        if not isinstance(self.budget, BudgetPolicy):
            raise RecordError(FailureCode.INVALID_TYPE, "plan.budget must be a BudgetPolicy")
        require_tuple(self.node_plan, "plan.node_plan", max_length=len(NODE_PLAN))
        if self.node_plan != NODE_PLAN:
            raise RecordError(
                FailureCode.BINDING_MISMATCH, "the trust spine graph is fixed and closed"
            )

    @property
    def canonical(self) -> CanonicalMap:
        return CanonicalMap(
            (
                ("budget", self.budget.canonical),
                ("kind", self.KIND),
                ("node_plan", tuple(str(node) for node in self.node_plan)),
                ("policy_config", self.policy_config.canonical),
                ("request", self.request.canonical),
            )
        )

    @property
    def plan_digest(self) -> str:
        return self.digest

    @property
    def tenant_id(self) -> str:
        return self.request.tenant_id

    @property
    def run_id(self) -> str:
        return self.request.run_id

    @property
    def source_digest(self) -> str:
        return self.request.source_digest

    @property
    def payload(self) -> CanonicalMap:
        return self.request.payload


def derive_idempotency_key(
    *,
    tenant_id: str,
    run_id: str,
    source_digest: str,
    node: NodeName,
    input_digest: str,
    attempt: int = 0,
) -> str:
    """Stable node idempotency key.

    The key is a pure function of the bound input, so the same node with the
    same input always yields the same key across crashes and replays.
    """
    require_match(tenant_id, TENANT_RE, "tenant_id")
    require_match(run_id, RUN_ID_RE, "run_id")
    require_digest(source_digest, "source_digest")
    require_digest(input_digest, "input_digest")
    if not isinstance(node, NodeName):
        raise RecordError(FailureCode.INVALID_TYPE, "node must be a NodeName")
    require_int(attempt, "attempt", minimum=0, maximum=MAX_REPAIRS + 1)
    material = digest_of(
        (
            "trust_spine.idempotency.v1",
            tenant_id,
            run_id,
            source_digest,
            str(node),
            input_digest,
            attempt,
        )
    )
    return "idk:" + material.split(":", 1)[1]


def derive_effect_key(
    *,
    tenant_id: str,
    run_id: str,
    source_digest: str,
    node: NodeName,
    plan_digest: str,
    proposal_digest: str,
    seal_digest: str,
    input_digest: str,
) -> str:
    """Stable idempotency key for one externally observable node.

    The key binds tenant + run + node + the *full* plan digest + the *full*
    proposal digest + the seal digest + this node's input digest. Every
    component is validated at full length, so a truncated or normalised digest
    cannot produce a colliding key: it produces a terminal failure instead.

    Because the key is a pure function of durable, immutable material, the same
    node re-executed after any crash presents the same key to the same port,
    which is what makes a duplicate effect impossible at the port.
    """
    require_match(tenant_id, TENANT_RE, "tenant_id")
    require_match(run_id, RUN_ID_RE, "run_id")
    if not isinstance(node, NodeName):
        raise RecordError(FailureCode.INVALID_TYPE, "node must be a NodeName")
    if node not in SIDE_EFFECT_NODES:
        raise RecordError(
            FailureCode.BINDING_MISMATCH, "effect keys are only defined for side-effect nodes"
        )
    require_digest(source_digest, "source_digest")
    require_digest(plan_digest, "plan_digest")
    require_digest(proposal_digest, "proposal_digest")
    require_digest(seal_digest, "seal_digest")
    require_digest(input_digest, "input_digest")
    material = digest_of(
        (
            "trust_spine.effect_idempotency.v1",
            tenant_id,
            run_id,
            source_digest,
            str(node),
            plan_digest,
            proposal_digest,
            seal_digest,
            input_digest,
        )
    )
    return "idk:" + material.split(":", 1)[1]


def derive_approval_key(
    *,
    tenant_id: str,
    run_id: str,
    source_digest: str,
    stage: Stage,
    subject_digest: str,
    plan_digest: str,
) -> str:
    """Stable idempotency key for one approval boundary.

    The stage and the subject are both bound, so a simulation approval can
    never be presented as the production approval: its key will not match the
    key the runtime expects at the production boundary.
    """
    require_match(tenant_id, TENANT_RE, "tenant_id")
    require_match(run_id, RUN_ID_RE, "run_id")
    require_digest(source_digest, "source_digest")
    if not isinstance(stage, Stage):
        raise RecordError(FailureCode.INVALID_TYPE, "stage must be a Stage")
    require_digest(subject_digest, "subject_digest")
    require_digest(plan_digest, "plan_digest")
    material = digest_of(
        (
            "trust_spine.approval_idempotency.v1",
            tenant_id,
            run_id,
            source_digest,
            str(stage),
            subject_digest,
            plan_digest,
        )
    )
    return "idk:" + material.split(":", 1)[1]


def error_canonical(error: BaseException) -> CanonicalMap:
    """Canonical, digestible representation of any failure."""
    if isinstance(error, TrustSpineError):
        code = str(error.code)
    else:
        code = str(FailureCode.ADAPTER_FAILURE)
    message = str(error)
    if len(message) > MAX_TEXT_LENGTH:
        message = message[:MAX_TEXT_LENGTH]
    return CanonicalMap(
        (
            ("code", code),
            ("error_type", type(error).__name__),
            ("kind", "error"),
            ("message", message),
        )
    )


def error_digest(error: BaseException) -> str:
    return digest_of(error_canonical(error))
