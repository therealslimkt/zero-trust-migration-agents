from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_runtime.graph import (
    GraphEvent,
    GraphPhase,
    GraphSnapshot,
    GraphStatus,
    ResumeInput,
)
from agent_runtime.collaboration import Portfolio, SourceFamily
from agent_runtime.collaboration import SourceInstance as CollaborativeSource
from agent_runtime.dynamic import DynamicValidationError
from agent_runtime.integration import portfolio_to_dynamic_sources
from agent_runtime.m3_integration import (
    JoinedRuntimeViolation,
    JournalName,
    ReadyFrozenPlan,
    TrustSpineCoordinator,
    project_graph_event,
    project_trust_spine_record,
)
from agent_runtime.ports import ContractDocument
from agent_runtime.trust_spine import NodeName, NodeStatus
from tests.agent_runtime.test_m3_trust_spine import Harness
from tests.contracts.schema_tools import ContractValidator


TRACE_ID = "c" * 32
TASK_ID = "task_JOINEDRUNTIME01"
TIMESTAMP = "2026-08-30T20:00:00Z"


def thaw(value):
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [thaw(item) for item in value]
    return value


def ready_snapshot(plan) -> GraphSnapshot:
    event = GraphEvent(
        sequence=1,
        event_type="route_selected",
        node_id="route_plan",
        operation_id="op_" + "1" * 64,
        detail={"selected_edge": "READY", "repair_count": "0"},
    )
    return GraphSnapshot(
        tenant_id=plan.tenant_id,
        run_id=plan.run_id,
        binding_digest=plan.plan_digest,
        revision=1,
        phase=GraphPhase.COMPLETE,
        status=GraphStatus.SUCCEEDED,
        events=(event,),
    )


def validate(document: ContractDocument) -> None:
    ContractValidator(Path("contracts/v2/schemas/a2a-event.schema.json")).validate(
        thaw(document.payload)
    )


def test_ready_frozen_handoff_is_the_only_coordinator_entrance():
    harness = Harness()
    handoff = ReadyFrozenPlan.from_snapshot(ready_snapshot(harness.plan), harness.plan)
    result = TrustSpineCoordinator(harness.runtime).execute(handoff)
    assert result.request_digest == harness.plan.request.request_digest

    generic_resume = ResumeInput(
        interrupt_id="int_" + "a" * 64,
        checkpoint_id="ckpt_" + "b" * 64,
        idempotency_key="resume-key-joined",
        text="approved",
    )
    a2a = ContractDocument("urn:test:a2a", {"type": "approval"})
    coordinator = TrustSpineCoordinator(harness.runtime)
    for value in (generic_resume, a2a, harness.plan):
        with pytest.raises(JoinedRuntimeViolation, match="coordinator_handoff"):
            coordinator.execute(value)  # type: ignore[arg-type]


def test_handoff_requires_ready_state_and_exact_full_plan_binding():
    harness = Harness()
    ready = ready_snapshot(harness.plan)
    with pytest.raises(JoinedRuntimeViolation, match="handoff_plan_binding"):
        ReadyFrozenPlan.from_snapshot(
            GraphSnapshot(
                tenant_id=ready.tenant_id,
                run_id=ready.run_id,
                binding_digest="sha256:" + "f" * 64,
                revision=ready.revision,
                phase=ready.phase,
                status=ready.status,
                events=ready.events,
            ),
            harness.plan,
        )
    with pytest.raises(JoinedRuntimeViolation, match="handoff_not_ready"):
        ReadyFrozenPlan.from_snapshot(
            GraphSnapshot(
                tenant_id=ready.tenant_id,
                run_id=ready.run_id,
                binding_digest=ready.binding_digest,
                phase=GraphPhase.PLANNING,
            ),
            harness.plan,
        )


def test_postgres_authority_joins_both_journals_into_contract_valid_replay():
    harness = Harness()
    graph = ready_snapshot(harness.plan)
    graph_projection = project_graph_event(
        graph,
        graph.events[0],
        postgres_sequence=41,
        trace_id=TRACE_ID,
        task_id=TASK_ID,
        timestamp=TIMESTAMP,
    )
    assert graph_projection.journal is JournalName.M2_GRAPH
    assert graph_projection.local_sequence == 1
    graph_payload = thaw(graph_projection.document.payload)
    assert graph_payload["sequence"] == 41
    assert graph_payload["from"] == "mission_control"
    assert graph_payload["orchestration"]["route"]["selectedEdge"] == "ready"
    validate(graph_projection.document)

    harness.execute()
    record = next(
        item
        for item in harness.store.load_node_records(
            harness.plan.tenant_id, harness.plan.run_id
        )
        if item.node is NodeName.FLOW_DISPATCH and item.status is NodeStatus.SUCCEEDED
    )
    trust_projection = project_trust_spine_record(
        record,
        postgres_sequence=42,
        trace_id=TRACE_ID,
        task_id=TASK_ID,
        timestamp=TIMESTAMP,
    )
    assert trust_projection.journal is JournalName.M3_TRUST_SPINE
    assert trust_projection.local_sequence == record.sequence
    trust_payload = thaw(trust_projection.document.payload)
    assert trust_payload["sequence"] == 42
    assert "implementationId:flow.dispatch" in trust_payload["contextRefs"]
    validate(trust_projection.document)

    # Replaying identical authoritative inputs is byte-for-byte deterministic.
    assert (
        project_graph_event(
            graph,
            graph.events[0],
            postgres_sequence=41,
            trace_id=TRACE_ID,
            task_id=TASK_ID,
            timestamp=TIMESTAMP,
        )
        == graph_projection
    )


def test_graph_approval_interrupt_projects_as_human_approval_required():
    harness = Harness()
    event = GraphEvent(
        sequence=1,
        event_type="interrupt_requested",
        node_id="request_input",
        operation_id="op_" + "2" * 64,
        detail={
            "interrupt_id": "int_" + "3" * 64,
            "kind": "production_approval",
        },
    )
    snapshot = GraphSnapshot(
        tenant_id=harness.plan.tenant_id,
        run_id=harness.plan.run_id,
        binding_digest=harness.plan.plan_digest,
        revision=1,
        events=(event,),
    )
    projection = project_graph_event(
        snapshot,
        event,
        postgres_sequence=7,
        trace_id=TRACE_ID,
        task_id=TASK_ID,
        timestamp=TIMESTAMP,
    )
    payload = thaw(projection.document.payload)
    assert payload["status"] == "blocked"
    assert payload["requiresHumanApproval"] is True
    assert payload["payload"]["payloadKind"] == "interrupt_request"
    validate(projection.document)


def test_collaboration_identifier_outside_dynamic_domain_is_never_normalized():
    source_id = "JDE:Primary"
    portfolio = Portfolio(
        run_id="run_JOINEDRUNTIME01",
        session_id="ses_JOINEDRUNTIME01",
        objective="Prove the exact cross-domain identifier boundary",
        sources=(CollaborativeSource(source_id, SourceFamily.JDE),),
    )
    documents = {
        source_id: ContractDocument("urn:test:sanitized", {"source": "jde"})
    }
    with pytest.raises(DynamicValidationError, match="source_instance_id"):
        portfolio_to_dynamic_sources(portfolio, sanitized_requests=documents)
    assert portfolio.sources[0].source_instance_id == source_id
