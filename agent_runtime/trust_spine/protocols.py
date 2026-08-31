"""Narrow injection ports for the trust spine.

Every external capability the runtime uses is expressed as a narrow Protocol
with typed record arguments. There are no cloud clients here, and no port
accepts a free-form string as an execution target:

* :class:`ModelRepairAdapter` is pre-approval only and returns *data*.
* :class:`StateStore` is the durable authority for records, checkpoints and the
  final result.
* :class:`ApprovalAuthority` is the only source of approval records.
* :class:`TemplateDispatcher` owns registry template identity and dispatch.
* :class:`ReconciliationReader` reads ledger reconciliation for a receipt.
* :class:`CertificationPort` holds signing/release authority, and nothing else.

The package intentionally ships **no** in-memory or ambient implementation of
any of these ports: a caller must inject one.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import (
    ApprovalQuery,
    ApprovalRecord,
    CanonicalMap,
    Certificate,
    CertificationRequest,
    DispatchReceipt,
    DispatchRequest,
    NodeRecord,
    ReconciliationQuery,
    ReconciliationReport,
    RegistryTemplate,
    RepairRequest,
    RunCheckpoint,
    RunResult,
)

__all__ = [
    "ApprovalAuthority",
    "CertificationPort",
    "ModelCapable",
    "ModelRepairAdapter",
    "ReconciliationReader",
    "StateStore",
    "TemplateDispatcher",
]


@runtime_checkable
class ModelCapable(Protocol):
    """Structural marker for anything that can enter a model boundary.

    Used by the sealed post-approval execution object to prove that no callable
    model provider is reachable from the post-production path.
    """

    def repair(self, request: RepairRequest) -> CanonicalMap:  # pragma: no cover - protocol
        ...


class ModelRepairAdapter(Protocol):
    """Pre-approval-only model boundary.

    The adapter receives a closed :class:`RepairRequest` and must return data
    only: a :class:`CanonicalMap` proposal payload. It is never given a
    callable, a tool, or the ability to act. It is dropped from the runtime
    path before the production approval boundary.
    """

    @property
    def adapter_id(self) -> str:
        """Stable principal identifier for separation-of-duty checks."""

    def repair(self, request: RepairRequest) -> CanonicalMap:
        """Return a repaired candidate payload. May raise; failures are recorded."""


class StateStore(Protocol):
    """Durable append/checkpoint state. The authority for crash recovery."""

    def append_node_record(self, record: NodeRecord) -> None:
        """Durably append one node record. Must be atomic per record."""

    def load_node_records(self, tenant_id: str, run_id: str) -> tuple[NodeRecord, ...]:
        """Return all node records for the run in append order."""

    def append_approval(self, record: ApprovalRecord) -> None:
        """Durably append one non-production approval record."""

    def commit_production_approval(
        self,
        expected_checkpoint: RunCheckpoint,
        record: ApprovalRecord,
        sealed_checkpoint: RunCheckpoint,
    ) -> None:
        """Atomically append production approval and seal the checkpoint.

        A production adapter must implement this as one transactional,
        compare-and-swap commit against ``expected_checkpoint``.  The intended
        authority is Cloud SQL/PostgreSQL; analytics stores are not valid
        implementations of this port.
        """

    def load_approvals(self, tenant_id: str, run_id: str) -> tuple[ApprovalRecord, ...]:
        """Return all approval records for the run in append order."""

    def write_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        """Durably replace the resumable checkpoint for the run."""

    def load_checkpoint(self, tenant_id: str, run_id: str) -> RunCheckpoint | None:
        """Return the latest checkpoint, or ``None`` if the run is unseen."""

    def store_result(self, result: RunResult) -> None:
        """Durably store the terminal result exactly once."""

    def load_result(self, tenant_id: str, run_id: str) -> RunResult | None:
        """Return the terminal result if the run already completed."""


class ApprovalAuthority(Protocol):
    """Authenticated approval reader/resolver.

    Approval records enter the runtime through this port and nowhere else. The
    authority authenticates the approver; the runtime verifies the bindings.
    """

    @property
    def authority_id(self) -> str:
        """Stable principal identifier of the approval authority."""

    def fetch_approval(self, query: ApprovalQuery) -> ApprovalRecord | None:
        """Return the decision for this exact stage and subject, if any."""


class TemplateDispatcher(Protocol):
    """Registered template dispatcher.

    ``resolve_template`` is the registry read: it maps an allowlisted
    identity/version to the registry-owned record that carries the parameter
    specifications and the opaque handle fingerprint. ``dispatch`` executes the
    registry-held handle. No method accepts a command, module, SQL statement,
    path, image reference, expression or arbitrary executor target.
    """

    @property
    def dispatcher_id(self) -> str:
        """Stable principal identifier of the dispatcher."""

    def resolve_template(self, template_id: str, template_version: str) -> RegistryTemplate:
        """Return the registry record, or raise if the identity is unregistered."""

    def dispatch(self, request: DispatchRequest) -> DispatchReceipt:
        """Dispatch the sealed bundle. Must be idempotent on the request key."""


class ReconciliationReader(Protocol):
    """Ledger reconciliation reader. Read-only with respect to effects."""

    @property
    def reader_id(self) -> str:
        """Stable principal identifier of the ledger reader."""

    def read_reconciliation(self, query: ReconciliationQuery) -> ReconciliationReport:
        """Return the reconciliation for a dispatched effect."""


class CertificationPort(Protocol):
    """Forge certification signer / release port.

    This is the only holder of signing and release authority. It must not be
    the same principal or object as the dispatcher, the ledger reader, or any
    pre-approval model component.
    """

    @property
    def signer_id(self) -> str:
        """Stable principal identifier of the signer."""

    def sign_and_release(self, request: CertificationRequest) -> Certificate:
        """Sign the chain and release. Must be idempotent on the request key."""
