"""Dependency-inversion ports for the production agent runtime.

The records in this module are private adapter SPI, not public workflow or API
contracts.  Canonical documents stay owned by ``contracts/`` and cross this
boundary as an immutable ``ContractDocument`` carrying their schema identifier.

All ports are asynchronous because production implementations perform remote
I/O.  This package intentionally ships no in-memory or cloud implementation.
Tests supply small fakes at the composition boundary.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Protocol, Union, runtime_checkable


JsonScalar = Union[None, bool, int, float, str]
JsonValue = Union[JsonScalar, Mapping[str, "JsonValue"], Sequence["JsonValue"]]
JsonObject = Mapping[str, JsonValue]

_SCHEMA_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._:/-]{0,255}$")
_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


class RuntimeBoundaryError(ValueError):
    """A safe, repository-owned boundary validation failure."""


def _freeze_json(value: object, *, depth: int = 0) -> JsonValue:
    if depth > 64:
        raise RuntimeBoundaryError("document_depth")
    if value is None or type(value) in (bool, int, str):
        return value  # type: ignore[return-value]
    if type(value) is float:
        if not math.isfinite(value):
            raise RuntimeBoundaryError("document_number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise RuntimeBoundaryError("document_key")
            frozen[key] = _freeze_json(item, depth=depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item, depth=depth + 1) for item in value)
    raise RuntimeBoundaryError("document_value")


def _require_text(value: str, code: str) -> None:
    if type(value) is not str or not value or len(value) > 2048:
        raise RuntimeBoundaryError(code)


@dataclasses.dataclass(frozen=True)
class ContractDocument:
    """An immutable carrier for a separately validated canonical document."""

    schema_id: str
    payload: JsonObject = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        if type(self.schema_id) is not str or _SCHEMA_ID_RE.fullmatch(self.schema_id) is None:
            raise RuntimeBoundaryError("schema_id")
        if not isinstance(self.payload, Mapping):
            raise RuntimeBoundaryError("document")
        frozen = _freeze_json(self.payload)
        if not isinstance(frozen, Mapping):  # defensive; payload is checked above
            raise RuntimeBoundaryError("document")
        object.__setattr__(self, "payload", frozen)


@dataclasses.dataclass(frozen=True)
class VersionedDocument:
    """A canonical state document with an optimistic-concurrency revision."""

    revision: int
    document: ContractDocument

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 0:
            raise RuntimeBoundaryError("state_revision")
        if not isinstance(self.document, ContractDocument):
            raise RuntimeBoundaryError("state_document")


@dataclasses.dataclass(frozen=True)
class ArtifactLocation:
    """An immutable content-addressed artifact reference."""

    uri: str
    digest: str
    media_type: str
    size_bytes: int

    def __post_init__(self) -> None:
        _require_text(self.uri, "artifact_uri")
        if type(self.digest) is not str or _DIGEST_RE.fullmatch(self.digest) is None:
            raise RuntimeBoundaryError("artifact_digest")
        _require_text(self.media_type, "artifact_media_type")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise RuntimeBoundaryError("artifact_size")


@runtime_checkable
class StateStore(Protocol):
    """Authoritative lifecycle state with compare-and-set persistence."""

    async def load(self, *, tenant_id: str, run_id: str) -> VersionedDocument | None: ...

    async def compare_and_set(
        self,
        *,
        tenant_id: str,
        run_id: str,
        expected_revision: int | None,
        document: ContractDocument,
    ) -> VersionedDocument: ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Create-once artifact persistence; implementations must verify digests."""

    async def put_immutable(
        self,
        *,
        tenant_id: str,
        run_id: str,
        artifact_name: str,
        payload: bytes,
        media_type: str,
        expected_digest: str,
    ) -> ArtifactLocation: ...

    async def read(self, *, tenant_id: str, location: ArtifactLocation) -> bytes: ...


@runtime_checkable
class ModelProvider(Protocol):
    """Structured model invocation over sanitized, schema-bound documents."""

    async def generate(
        self,
        *,
        tenant_id: str,
        run_id: str,
        request: ContractDocument,
        response_schema_id: str,
    ) -> ContractDocument: ...


@runtime_checkable
class EventSink(Protocol):
    """Append a sanitized canonical event to the durable event stream."""

    async def append(self, *, event: ContractDocument) -> int: ...


@runtime_checkable
class ApprovalAuthority(Protocol):
    """Verify approval evidence against the canonical expectation document."""

    async def require_verified(
        self,
        *,
        expectation: ContractDocument,
        evidence: ContractDocument,
    ) -> ContractDocument: ...


@runtime_checkable
class Executor(Protocol):
    """Execute an allowlisted command with already-verified approval evidence."""

    async def execute(
        self,
        *,
        command: ContractDocument,
        verified_approval: ContractDocument,
    ) -> ContractDocument: ...


@dataclasses.dataclass(frozen=True)
class RuntimePorts:
    """Complete production dependency set injected into the ADK root factory."""

    state: StateStore
    artifacts: ArtifactStore
    models: ModelProvider
    events: EventSink
    approvals: ApprovalAuthority
    executor: Executor

    def __post_init__(self) -> None:
        required = (
            ("state", self.state, StateStore),
            ("artifacts", self.artifacts, ArtifactStore),
            ("models", self.models, ModelProvider),
            ("events", self.events, EventSink),
            ("approvals", self.approvals, ApprovalAuthority),
            ("executor", self.executor, Executor),
        )
        for name, value, protocol in required:
            if not isinstance(value, protocol):
                raise TypeError(f"runtime_port_{name}")
