"""Journaled catalog-first graph execution with deterministic resume."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from collections.abc import Awaitable, Callable
from typing import Protocol

from .model import (
    CatalogProbe,
    CatalogProbeKind,
    CatalogRoute,
    GraphEvent,
    GraphInvariantError,
    GraphPhase,
    GraphSnapshot,
    GraphStatus,
    InterruptKind,
    InterruptRequest,
    ResumeInput,
)
from .routes import route_catalog


class GraphConflictError(RuntimeError):
    """The persisted revision changed or a resume did not match the pause."""


class SnapshotStore(Protocol):
    async def load(self, *, tenant_id: str, run_id: str) -> GraphSnapshot | None: ...

    async def compare_and_set(
        self, *, expected_revision: int | None, snapshot: GraphSnapshot
    ) -> GraphSnapshot: ...


Probe = Callable[[str], Awaitable[CatalogProbe]]
ValidateIntent = Callable[[str], Awaitable[None]]
AfterCommit = Callable[[GraphSnapshot], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class CatalogCallbacks:
    validate_intent: ValidateIntent
    metadata: Probe
    vector: Probe
    access: Probe


class CatalogGraphKernel:
    """Runs the deterministic portion of the catalog-first fixed graph.

    Each callback receives a stable operation ID.  Adapters must use that ID as
    their idempotency key.  A crash after a commit therefore fast-forwards the
    completed node; a crash before a commit may retry the same operation ID.
    """

    def __init__(
        self,
        *,
        store: SnapshotStore,
        callbacks: CatalogCallbacks,
        after_commit: AfterCommit | None = None,
    ) -> None:
        self._store = store
        self._callbacks = callbacks
        self._after_commit = after_commit

    async def run(self, *, tenant_id: str, run_id: str) -> GraphSnapshot:
        state = await self._store.load(tenant_id=tenant_id, run_id=run_id)
        if state is None:
            state = GraphSnapshot(tenant_id=tenant_id, run_id=run_id)
            state = await self._commit(None, state, "run_started", "validate_intent")
        if state.phase is GraphPhase.NEW:
            await self._callbacks.validate_intent(self._operation(run_id, "validate_intent"))
            state = dataclasses.replace(state, phase=GraphPhase.VALIDATED)
            state = await self._commit(state.revision, state, "node_succeeded", "validate_intent")
        if state.phase is GraphPhase.VALIDATED:
            state = await self._run_probes(state)
        if state.phase is GraphPhase.PROBED:
            if {probe.kind for probe in state.probes} != frozenset(CatalogProbeKind):
                return await self._fail(state, "catalog_join_incomplete")
            state = dataclasses.replace(state, phase=GraphPhase.JOINED)
            state = await self._commit(state.revision, state, "join_completed", "catalog_join")
        if state.phase is GraphPhase.JOINED:
            selected = route_catalog(state.probes)
            failed = selected is CatalogRoute.FAIL_CLOSED
            state = dataclasses.replace(
                state,
                phase=GraphPhase.FAILED if failed else GraphPhase.ROUTED,
                status=GraphStatus.FAILED if failed else GraphStatus.SUCCEEDED,
                catalog_route=selected,
            )
            state = await self._commit(
                state.revision,
                state,
                "route_selected" if not failed else "route_failed_closed",
                "route_catalog",
                detail={"selected_edge": selected.value},
            )
        return state

    async def request_interrupt(
        self,
        *,
        tenant_id: str,
        run_id: str,
        kind: InterruptKind,
        subject_digest: str | None = None,
    ) -> GraphSnapshot:
        state = await self._require_state(tenant_id, run_id)
        if state.pending_interrupt is not None:
            if state.pending_interrupt.kind is kind:
                return state
            raise GraphConflictError("pending_interrupt")
        ordinal = 1 + sum(
            event.event_type == "interrupt_requested" for event in state.events
        )
        interrupt = InterruptRequest(
            interrupt_id=self._interrupt_id(run_id, kind, ordinal),
            kind=kind,
            checkpoint_id=state.checkpoint_id,
            ordinal=ordinal,
            subject_digest=subject_digest,
        )
        status = (
            GraphStatus.AWAITING_INPUT
            if kind is InterruptKind.CLARIFICATION
            else GraphStatus.AWAITING_APPROVAL
        )
        paused = dataclasses.replace(
            state, phase=GraphPhase.PAUSED, status=status, pending_interrupt=interrupt
        )
        return await self._commit(
            state.revision,
            paused,
            "interrupt_requested",
            "request_input",
            detail={"interrupt_id": interrupt.interrupt_id, "kind": kind.value},
        )

    async def resume(self, *, tenant_id: str, run_id: str, value: ResumeInput) -> GraphSnapshot:
        state = await self._require_state(tenant_id, run_id)
        if value.idempotency_key in state.consumed_idempotency_keys:
            receipts = dict(state.resume_digests)
            if receipts[value.idempotency_key] != value.request_digest:
                raise GraphConflictError("idempotency_key_reused")
            return state
        pending = state.pending_interrupt
        if pending is None:
            raise GraphConflictError("run_not_paused")
        if pending.kind is not InterruptKind.CLARIFICATION:
            raise GraphConflictError("approval_not_resumable_via_input")
        if value.interrupt_id != pending.interrupt_id:
            raise GraphConflictError("interrupt_mismatch")
        if value.checkpoint_id != pending.checkpoint_id:
            raise GraphConflictError("checkpoint_mismatch")
        resumed = dataclasses.replace(
            state,
            phase=GraphPhase.VALIDATED,
            status=GraphStatus.RUNNING,
            pending_interrupt=None,
            consumed_idempotency_keys=state.consumed_idempotency_keys
            | {value.idempotency_key},
            resume_digests=state.resume_digests
            + ((value.idempotency_key, value.request_digest),),
        )
        return await self._commit(
            state.revision,
            resumed,
            "interrupt_resumed",
            "request_input",
            detail={"interrupt_id": pending.interrupt_id},
        )

    async def _run_probes(self, state: GraphSnapshot) -> GraphSnapshot:
        existing = {probe.kind: probe for probe in state.probes}
        callbacks = (
            (CatalogProbeKind.METADATA, self._callbacks.metadata),
            (CatalogProbeKind.VECTOR, self._callbacks.vector),
            (CatalogProbeKind.ACCESS, self._callbacks.access),
        )
        pending = [(kind, callback) for kind, callback in callbacks if kind not in existing]
        results = await asyncio.gather(
            *(
                callback(self._operation(state.run_id, f"catalog_{kind.value}"))
                for kind, callback in pending
            )
        )
        # Persist in graph order, never completion order, for byte-stable replay.
        for (kind, _), result in zip(pending, results):
            if result.kind is not kind:
                return await self._fail(state, "catalog_probe_kind_mismatch")
            existing[kind] = result
            ordered = tuple(existing[item] for item in CatalogProbeKind if item in existing)
            state = dataclasses.replace(state, probes=ordered)
            state = await self._commit(
                state.revision, state, "node_succeeded", f"catalog_{kind.value}"
            )
        state = dataclasses.replace(state, phase=GraphPhase.PROBED)
        return await self._commit(
            state.revision, state, "fanout_completed", "catalog_fanout"
        )

    async def _fail(self, state: GraphSnapshot, code: str) -> GraphSnapshot:
        failed = dataclasses.replace(
            state,
            phase=GraphPhase.FAILED,
            status=GraphStatus.FAILED,
            catalog_route=CatalogRoute.FAIL_CLOSED,
        )
        return await self._commit(
            state.revision,
            failed,
            "graph_failed",
            "catalog_graph",
            detail={"reason_code": code},
        )

    async def _require_state(self, tenant_id: str, run_id: str) -> GraphSnapshot:
        state = await self._store.load(tenant_id=tenant_id, run_id=run_id)
        if state is None:
            raise GraphConflictError("run_not_found")
        return state

    async def _commit(
        self,
        expected_revision: int | None,
        state: GraphSnapshot,
        event_type: str,
        node_id: str,
        *,
        detail: dict[str, str] | None = None,
    ) -> GraphSnapshot:
        event = GraphEvent(
            sequence=state.next_sequence,
            event_type=event_type,
            node_id=node_id,
            operation_id=self._operation(state.run_id, node_id),
            model_calls=0,
            detail=detail or {},
        )
        candidate = dataclasses.replace(
            state, revision=state.revision + 1, events=state.events + (event,)
        )
        persisted = await self._store.compare_and_set(
            expected_revision=expected_revision, snapshot=candidate
        )
        if self._after_commit is not None:
            await self._after_commit(persisted)
        return persisted

    @staticmethod
    def _operation(run_id: str, node_id: str) -> str:
        digest = hashlib.sha256(f"{run_id}:{node_id}".encode()).hexdigest()[:20]
        return f"op_{digest}"

    @staticmethod
    def _interrupt_id(run_id: str, kind: InterruptKind, ordinal: int) -> str:
        digest = hashlib.sha256(f"{run_id}:{kind.value}:{ordinal}".encode()).hexdigest()[:20]
        return f"int_{digest}"
