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
    PlanRoute,
    PlanRouteInput,
    ResumeInput,
)
from .routes import route_catalog, route_plan


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
            state = await self._commit(None, state, "run_started", "catalog_graph")
        if self._is_terminal(state) or state.phase is GraphPhase.PAUSED:
            return state
        if state.phase is GraphPhase.NEW:
            await self._callbacks.validate_intent(self._operation(run_id, "validate_intent"))
            state = dataclasses.replace(state, phase=GraphPhase.VALIDATED)
            state = await self._commit(
                state.revision,
                state,
                "node_succeeded",
                "validate_intent",
                operation_id=self._operation(run_id, "validate_intent"),
            )
        if state.phase is GraphPhase.VALIDATED:
            state = await self._run_probes(state)
        if state.phase is GraphPhase.PROBED:
            if {probe.kind for probe in state.probes} != frozenset(CatalogProbeKind):
                return await self._fail(state, "catalog_join_incomplete")
            state = dataclasses.replace(state, phase=GraphPhase.JOINED)
            state = await self._commit(state.revision, state, "join_completed", "catalog_join")
        if state.phase is GraphPhase.JOINED:
            selected = route_catalog(state.probes)
            state = dataclasses.replace(state, catalog_route=selected)
            if selected is CatalogRoute.NEEDS_INPUT:
                return await self._pause(
                    state=state,
                    kind=InterruptKind.CLARIFICATION,
                    preceding_route=("route_catalog", selected.value),
                )
            if selected is CatalogRoute.FAIL_CLOSED:
                state = dataclasses.replace(
                    state, phase=GraphPhase.FAILED, status=GraphStatus.FAILED
                )
            elif selected is not CatalogRoute.NEEDS_INPUT:
                state = dataclasses.replace(
                    state, phase=GraphPhase.ROUTED, status=GraphStatus.SUCCEEDED
                )
            state = await self._commit(
                state.revision,
                state,
                "route_selected"
                if selected is not CatalogRoute.FAIL_CLOSED
                else "route_failed_closed",
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
            if (
                state.pending_interrupt.kind is kind
                and state.pending_interrupt.subject_digest == subject_digest
            ):
                return state
            raise GraphConflictError("pending_interrupt")
        self._ensure_resumable(state)
        return await self._pause(
            state=state, kind=kind, subject_digest=subject_digest
        )

    async def apply_plan_route(
        self,
        *,
        tenant_id: str,
        run_id: str,
        value: PlanRouteInput,
    ) -> GraphSnapshot:
        """Apply a deterministic plan edge and persist bounded repair progress."""

        state = await self._require_state(tenant_id, run_id)
        self._ensure_mutable(state)
        if state.phase is not GraphPhase.PLANNING:
            raise GraphConflictError("plan_phase")
        selected = route_plan(value, repair_count=state.repair_count)
        if selected is PlanRoute.NEEDS_RESEARCH:
            state = dataclasses.replace(
                state, repair_count=state.repair_count + 1
            )
        elif selected is PlanRoute.NEEDS_INPUT:
            return await self._pause(
                state=state,
                kind=InterruptKind.CLARIFICATION,
                preceding_route=("route_plan", selected.value),
            )
        elif selected is PlanRoute.READY:
            state = dataclasses.replace(
                state, phase=GraphPhase.COMPLETE, status=GraphStatus.SUCCEEDED
            )
        else:
            state = dataclasses.replace(
                state, phase=GraphPhase.FAILED, status=GraphStatus.FAILED
            )
        return await self._commit(
            state.revision,
            state,
            "route_selected"
            if selected not in {PlanRoute.FAIL_CLOSED, PlanRoute.REJECTED}
            else "route_failed_closed",
            "route_plan",
            detail={
                "selected_edge": selected.value,
                "repair_count": str(state.repair_count),
            },
        )

    async def record_model_call(
        self,
        *,
        tenant_id: str,
        run_id: str,
        agent_id: str,
        invocation_id: str,
    ) -> GraphSnapshot:
        """Record exactly one observed call from an allowlisted model agent."""

        state = await self._require_state(tenant_id, run_id)
        self._ensure_mutable(state)
        allowed = {
            "atlas",
            "scout",
            "maven",
            "prisma",
            "jetty_advisor",
            "source_analyst_sap",
            "source_analyst_jde",
            "source_analyst_oracle",
            "source_analyst_cobol",
            "source_analyst_ibmi",
            "source_analyst_sage",
            "source_analyst_ax",
        }
        if agent_id not in allowed:
            raise GraphInvariantError("model_agent_id")
        if (
            type(invocation_id) is not str
            or not invocation_id.startswith("inv_")
            or len(invocation_id) < 16
        ):
            raise GraphInvariantError("model_invocation_id")
        if invocation_id in state.model_invocation_ids:
            return state
        state = dataclasses.replace(
            state,
            model_invocation_ids=state.model_invocation_ids | {invocation_id},
        )
        return await self._commit(
            state.revision,
            state,
            "model_call_observed",
            agent_id,
            operation_id=invocation_id,
            model_calls=1,
            detail={"invocation_id": invocation_id},
        )

    async def _pause(
        self,
        *,
        state: GraphSnapshot,
        kind: InterruptKind,
        subject_digest: str | None = None,
        preceding_route: tuple[str, str] | None = None,
    ) -> GraphSnapshot:
        ordinal = 1 + sum(
            event.event_type == "interrupt_requested" for event in state.events
        )
        interrupt = InterruptRequest(
            interrupt_id=self._interrupt_id(state.run_id, kind, ordinal),
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
            state,
            phase=GraphPhase.PAUSED,
            status=status,
            pending_interrupt=interrupt,
            paused_from_phase=state.phase,
        )
        if preceding_route is None:
            return await self._commit(
                state.revision,
                paused,
                "interrupt_requested",
                "request_input",
                detail={"interrupt_id": interrupt.interrupt_id, "kind": kind.value},
            )
        route_node, selected_edge = preceding_route
        route_event = GraphEvent(
            sequence=state.next_sequence,
            event_type="route_selected",
            node_id=route_node,
            operation_id=self._operation(
                state.run_id, f"{route_node}_{state.next_sequence}"
            ),
            detail={"selected_edge": selected_edge},
        )
        interrupt_event = GraphEvent(
            sequence=state.next_sequence + 1,
            event_type="interrupt_requested",
            node_id="request_input",
            operation_id=self._operation(
                state.run_id, f"request_input_{state.next_sequence + 1}"
            ),
            detail={"interrupt_id": interrupt.interrupt_id, "kind": kind.value},
        )
        candidate = dataclasses.replace(
            paused,
            revision=paused.revision + 1,
            events=paused.events + (route_event, interrupt_event),
        )
        persisted = await self._store.compare_and_set(
            expected_revision=state.revision, snapshot=candidate
        )
        if self._after_commit is not None:
            await self._after_commit(persisted)
        return persisted

    async def resume(self, *, tenant_id: str, run_id: str, value: ResumeInput) -> GraphSnapshot:
        state = await self._require_state(tenant_id, run_id)
        if value.idempotency_key in state.consumed_idempotency_keys:
            receipts = dict(state.resume_digests)
            if receipts[value.idempotency_key] != value.request_digest:
                raise GraphConflictError("idempotency_key_reused")
            return state
        if self._is_terminal(state):
            raise GraphConflictError("terminal_run")
        pending = state.pending_interrupt
        if pending is None:
            raise GraphConflictError("run_not_paused")
        if pending.kind is not InterruptKind.CLARIFICATION:
            raise GraphConflictError("approval_not_resumable_via_input")
        if value.interrupt_id != pending.interrupt_id:
            raise GraphConflictError("interrupt_mismatch")
        if value.checkpoint_id != pending.checkpoint_id:
            raise GraphConflictError("checkpoint_mismatch")
        if state.revision < 1 or pending.checkpoint_id != state.checkpoint_id_for_revision(
            state.revision - 1
        ):
            raise GraphConflictError("checkpoint_not_resumable")
        if state.paused_from_phase is None or not self._phase_resumable(
            state.paused_from_phase
        ):
            raise GraphConflictError("checkpoint_not_resumable")
        resumed = dataclasses.replace(
            state,
            phase=state.paused_from_phase,
            status=GraphStatus.RUNNING,
            pending_interrupt=None,
            paused_from_phase=None,
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
        tasks: dict[CatalogProbeKind, asyncio.Task[CatalogProbe]] = {}
        try:
            async with asyncio.TaskGroup() as group:
                for kind, callback in pending:
                    tasks[kind] = group.create_task(
                        callback(
                            self._operation(
                                state.run_id, f"catalog_{kind.value}"
                            )
                        ),
                        name=f"catalog_{kind.value}",
                    )
        except* Exception as errors:
            # TaskGroup has cancelled and awaited every sibling at this point.
            # Preserve the callback's original exception API when one probe
            # failed; concurrent independent failures remain an ExceptionGroup.
            if len(errors.exceptions) == 1:
                raise errors.exceptions[0]
            raise
        results = [tasks[kind].result() for kind, _ in pending]
        # Persist in graph order, never completion order, for byte-stable replay.
        for (kind, _), result in zip(pending, results):
            if result.kind is not kind:
                return await self._fail(state, "catalog_probe_kind_mismatch")
            existing[kind] = result
            ordered = tuple(existing[item] for item in CatalogProbeKind if item in existing)
            state = dataclasses.replace(state, probes=ordered)
            state = await self._commit(
                state.revision,
                state,
                "node_succeeded",
                f"catalog_{kind.value}",
                operation_id=self._operation(
                    state.run_id, f"catalog_{kind.value}"
                ),
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
        operation_id: str | None = None,
        model_calls: int = 0,
    ) -> GraphSnapshot:
        event = GraphEvent(
            sequence=state.next_sequence,
            event_type=event_type,
            node_id=node_id,
            operation_id=operation_id
            or self._operation(
                state.run_id, f"{node_id}_{state.next_sequence}"
            ),
            model_calls=model_calls,
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
    def _phase_resumable(phase: GraphPhase) -> bool:
        return phase in {
            GraphPhase.NEW,
            GraphPhase.VALIDATED,
            GraphPhase.PROBED,
            GraphPhase.JOINED,
            GraphPhase.PLANNING,
        }

    @classmethod
    def _is_terminal(cls, state: GraphSnapshot) -> bool:
        return state.status in {GraphStatus.SUCCEEDED, GraphStatus.FAILED} or state.phase in {
            GraphPhase.ROUTED,
            GraphPhase.COMPLETE,
            GraphPhase.FAILED,
        }

    @classmethod
    def _ensure_mutable(cls, state: GraphSnapshot) -> None:
        if cls._is_terminal(state):
            raise GraphConflictError("terminal_run")
        if state.phase is GraphPhase.PAUSED:
            raise GraphConflictError("run_paused")

    @classmethod
    def _ensure_resumable(cls, state: GraphSnapshot) -> None:
        cls._ensure_mutable(state)
        if not state.checkpoint.resumable:
            raise GraphConflictError("checkpoint_not_resumable")

    @staticmethod
    def _operation(run_id: str, node_id: str) -> str:
        digest = hashlib.sha256(f"{run_id}:{node_id}".encode()).hexdigest()[:20]
        return f"op_{digest}"

    @staticmethod
    def _interrupt_id(run_id: str, kind: InterruptKind, ordinal: int) -> str:
        digest = hashlib.sha256(f"{run_id}:{kind.value}:{ordinal}".encode()).hexdigest()[:20]
        return f"int_{digest}"
