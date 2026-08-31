"""Typed join from the Milestone 2 planning journal to the M3 trust spine.

This module is an application seam, not a deployed persistence adapter.
PostgreSQL supplies the authoritative cross-journal sequence; the pure
projection helpers below make replay deterministic once that sequence has
been transactionally assigned.
"""

from __future__ import annotations

import dataclasses
import enum
import re

from .graph import (
    CatalogRoute,
    GraphCheckpoint,
    GraphEvent,
    GraphPhase,
    GraphSnapshot,
    GraphStatus,
    PlanRoute,
)
from .ports import ContractDocument
from .telemetry import (
    DeterministicRoute,
    NodeObservation,
    ObservationStatus,
    SanitizedEventBridge,
    WorkflowPattern,
)
from .trust_spine import (
    FrozenPlan,
    NodeName,
    NodeRecord,
    NodeStatus,
    RunResult,
    TrustSpineRuntime,
    digest_of,
)


class JoinedRuntimeViolation(ValueError):
    """The M2/M3 boundary or its replay projection was not exact."""


class JournalName(str, enum.Enum):
    M2_GRAPH = "m2_graph"
    M3_TRUST_SPINE = "m3_trust_spine"


@dataclasses.dataclass(frozen=True, slots=True)
class ReadyFrozenPlan:
    """The only value accepted by the M2-to-M3 execution coordinator."""

    graph_checkpoint: GraphCheckpoint
    graph_journal_digest: str
    plan: FrozenPlan

    def __post_init__(self) -> None:
        if not isinstance(self.graph_checkpoint, GraphCheckpoint):
            raise JoinedRuntimeViolation("handoff_checkpoint")
        if (
            type(self.graph_journal_digest) is not str
            or re.fullmatch(r"sha256:[a-f0-9]{64}", self.graph_journal_digest) is None
        ):
            raise JoinedRuntimeViolation("handoff_journal_digest")
        if not isinstance(self.plan, FrozenPlan):
            raise JoinedRuntimeViolation("handoff_frozen_plan")
        if (
            self.graph_checkpoint.phase is not GraphPhase.COMPLETE
            or self.graph_checkpoint.resumable
            or self.graph_checkpoint.sequence < 1
        ):
            raise JoinedRuntimeViolation("handoff_not_ready")
        if (
            self.graph_checkpoint.tenant_id != self.plan.tenant_id
            or self.graph_checkpoint.run_id != self.plan.run_id
            or self.graph_checkpoint.binding_digest != self.plan.plan_digest
        ):
            raise JoinedRuntimeViolation("handoff_plan_binding")

    @classmethod
    def from_snapshot(
        cls, snapshot: GraphSnapshot, plan: FrozenPlan
    ) -> "ReadyFrozenPlan":
        if not isinstance(snapshot, GraphSnapshot) or not isinstance(plan, FrozenPlan):
            raise JoinedRuntimeViolation("handoff_type")
        if (
            snapshot.phase is not GraphPhase.COMPLETE
            or snapshot.status is not GraphStatus.SUCCEEDED
            or snapshot.pending_interrupt is not None
            or snapshot.checkpoint.resumable
        ):
            raise JoinedRuntimeViolation("handoff_not_ready")
        if (
            snapshot.tenant_id != plan.tenant_id
            or snapshot.run_id != plan.run_id
            or snapshot.binding_digest != plan.plan_digest
        ):
            raise JoinedRuntimeViolation("handoff_plan_binding")
        journal_digest = digest_of(
            (
                "m2.graph.journal.v1",
                snapshot.tenant_id,
                snapshot.run_id,
                snapshot.binding_digest,
                tuple(
                    (
                        event.sequence,
                        event.event_type,
                        event.node_id,
                        event.operation_id,
                        event.model_calls,
                        tuple(sorted(event.detail.items())),
                    )
                    for event in snapshot.events
                ),
            )
        )
        return cls(
            graph_checkpoint=snapshot.checkpoint,
            graph_journal_digest=journal_digest,
            plan=plan,
        )


class TrustSpineCoordinator:
    """Concrete, deliberately narrow entrance to ``TrustSpineRuntime``."""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: TrustSpineRuntime) -> None:
        if not isinstance(runtime, TrustSpineRuntime):
            raise TypeError("coordinator_runtime")
        self._runtime = runtime

    def execute(self, handoff: ReadyFrozenPlan) -> RunResult:
        # In particular, ResumeInput and ContractDocument/A2A values fail this
        # exact type boundary and cannot become plans by duck typing.
        if type(handoff) is not ReadyFrozenPlan:
            raise JoinedRuntimeViolation("coordinator_handoff")
        return self._runtime.execute(handoff.plan)


@dataclasses.dataclass(frozen=True, slots=True)
class PostgresJournalEvent:
    """One deterministic projection after PostgreSQL assigns global order.

    ``postgres_sequence`` is the replay cursor. ``local_sequence`` remains the
    source journal cursor. BigQuery may consume the resulting document, but it
    cannot assign, repair, or override either value.
    """

    postgres_sequence: int
    journal: JournalName
    local_sequence: int
    record_digest: str
    observation: NodeObservation

    def __post_init__(self) -> None:
        if type(self.postgres_sequence) is not int or self.postgres_sequence < 1:
            raise JoinedRuntimeViolation("postgres_sequence")
        if not isinstance(self.journal, JournalName):
            raise JoinedRuntimeViolation("journal_name")
        if type(self.local_sequence) is not int or self.local_sequence < 0:
            raise JoinedRuntimeViolation("journal_sequence")
        if (
            type(self.record_digest) is not str
            or re.fullmatch(r"sha256:[a-f0-9]{64}", self.record_digest) is None
        ):
            raise JoinedRuntimeViolation("journal_record_digest")
        if (
            not isinstance(self.observation, NodeObservation)
            or self.observation.sequence != self.postgres_sequence
            or self.observation.payload_digest != self.record_digest
        ):
            raise JoinedRuntimeViolation("journal_observation_binding")

    @property
    def document(self) -> ContractDocument:
        return SanitizedEventBridge.project(self.observation)


_CATALOG_EDGES = {
    CatalogRoute.EXISTING_ASSET.value: "existing_asset",
    CatalogRoute.NEEDS_INPUT.value: "needs_input",
    CatalogRoute.MIGRATE.value: "migrate",
    CatalogRoute.FAIL_CLOSED.value: "fail_closed",
}
_PLAN_EDGES = {
    PlanRoute.NEEDS_RESEARCH.value: "needs_research",
    PlanRoute.NEEDS_INPUT.value: "needs_input",
    PlanRoute.REJECTED.value: "rejected",
    PlanRoute.READY.value: "ready",
    PlanRoute.FAIL_CLOSED.value: "fail_closed",
}


def _node_run_id(*parts: object) -> str:
    return "nr_" + digest_of(("joined.node_run.v1",) + parts).split(":", 1)[1]


def _graph_record_digest(snapshot: GraphSnapshot, event: GraphEvent) -> str:
    return digest_of(
        (
            "m2.graph.event.v1",
            snapshot.tenant_id,
            snapshot.run_id,
            snapshot.binding_digest,
            event.sequence,
            event.event_type,
            event.node_id,
            event.operation_id,
            event.model_calls,
            tuple(sorted(event.detail.items())),
        )
    )


def project_graph_event(
    snapshot: GraphSnapshot,
    event: GraphEvent,
    *,
    postgres_sequence: int,
    trace_id: str,
    task_id: str,
    timestamp: str,
) -> PostgresJournalEvent:
    """Project one immutable M2 record under a PostgreSQL global sequence."""
    if not isinstance(snapshot, GraphSnapshot) or event not in snapshot.events:
        raise JoinedRuntimeViolation("graph_projection_record")
    digest = _graph_record_digest(snapshot, event)
    model_driven = event.model_calls == 1
    approval_required = (
        event.event_type == "interrupt_requested"
        and event.detail.get("kind") in {"simulation_approval", "production_approval"}
    )
    if approval_required or event.event_type == "interrupt_requested":
        status = ObservationStatus.BLOCKED
    elif event.event_type in {"graph_failed", "route_failed_closed"}:
        status = ObservationStatus.FAILED
    else:
        status = ObservationStatus.COMPLETE
    route: DeterministicRoute | None = None
    if event.node_id in {"route_catalog", "route_plan"} and "selected_edge" in event.detail:
        edges = _CATALOG_EDGES if event.node_id == "route_catalog" else _PLAN_EDGES
        selected_value = event.detail["selected_edge"]
        if selected_value not in edges:
            raise JoinedRuntimeViolation("graph_projection_route")
        route = DeterministicRoute(
            router_node_id=event.node_id,
            selected_edge=edges[selected_value],
            candidate_edges=tuple(edges.values()),
            reason_code=selected_value,
        )
    observation = NodeObservation(
        sequence=postgres_sequence,
        node_run_id=_node_run_id(
            JournalName.M2_GRAPH.value,
            snapshot.tenant_id,
            snapshot.run_id,
            event.sequence,
            digest,
        ),
        task_id=task_id,
        trace_id=trace_id,
        pattern=WorkflowPattern.GRAPH,
        node_path=(event.node_id,),
        attempt=1,
        isolation_scope="node_private",
        status=status,
        model_driven=model_driven,
        model_calls=event.model_calls,
        payload_digest=digest,
        timestamp=timestamp,
        agent_id=event.node_id if model_driven else None,
        route=route,
        implementation_id=None if model_driven else f"vale.{event.node_id}",
        approval_required=approval_required,
        journal_ref=f"{JournalName.M2_GRAPH.value}:{event.sequence}:{digest}",
    )
    return PostgresJournalEvent(
        postgres_sequence=postgres_sequence,
        journal=JournalName.M2_GRAPH,
        local_sequence=event.sequence,
        record_digest=digest,
        observation=observation,
    )


_IMPLEMENTATION_BY_NODE = {
    NodeName.PRISMA_VALIDATE: "prisma.validate",
    NodeName.PRISMA_REPAIR: "prisma.repair_result",
    NodeName.DETERMINISTIC_POLICY: "vale.deterministic_policy",
    NodeName.VALE_VERIFY: "vale.verify",
    NodeName.FLOW_DISPATCH: "flow.dispatch",
    NodeName.LEDGER_RECONCILE: "ledger.reconcile",
    NodeName.FORGE_CERTIFY: "forge.certify",
}


def project_trust_spine_record(
    record: NodeRecord,
    *,
    postgres_sequence: int,
    trace_id: str,
    task_id: str,
    timestamp: str,
) -> PostgresJournalEvent:
    """Project one immutable M3 record into the same PostgreSQL replay order."""
    if not isinstance(record, NodeRecord):
        raise JoinedRuntimeViolation("trust_projection_record")
    model_driven = record.model_call_delta == 1
    statuses = {
        NodeStatus.STARTED: ObservationStatus.RUNNING,
        NodeStatus.SUCCEEDED: ObservationStatus.COMPLETE,
        NodeStatus.FAILED: ObservationStatus.FAILED,
    }
    observation = NodeObservation(
        sequence=postgres_sequence,
        node_run_id=_node_run_id(
            JournalName.M3_TRUST_SPINE.value,
            record.tenant_id,
            record.run_id,
            record.sequence,
            record.digest,
        ),
        task_id=task_id,
        trace_id=trace_id,
        pattern=WorkflowPattern.GRAPH,
        node_path=(str(record.node),),
        attempt=record.attempt + 1,
        isolation_scope="node_private",
        status=statuses[record.status],
        model_driven=model_driven,
        model_calls=record.model_call_delta,
        payload_digest=record.digest,
        timestamp=timestamp,
        agent_id="prisma" if model_driven else None,
        implementation_id=None if model_driven else _IMPLEMENTATION_BY_NODE[record.node],
        journal_ref=(
            f"{JournalName.M3_TRUST_SPINE.value}:{record.sequence}:{record.digest}"
        ),
    )
    return PostgresJournalEvent(
        postgres_sequence=postgres_sequence,
        journal=JournalName.M3_TRUST_SPINE,
        local_sequence=record.sequence,
        record_digest=record.digest,
        observation=observation,
    )
