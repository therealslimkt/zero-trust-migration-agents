from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_runtime.telemetry import (
    NodeObservation,
    ObservationStatus,
    SanitizedEventBridge,
    TelemetryViolation,
    TraceAccountant,
    WorkflowPattern,
)
from tests.contracts.schema_tools import ContractValidator


def observation(sequence: int, *, model_driven: bool = False) -> NodeObservation:
    return NodeObservation(
        sequence=sequence,
        node_run_id=f"nr_NODEEXECUTION{sequence:04d}",
        task_id="task_ENTERPRISE01",
        trace_id="a" * 32,
        pattern=WorkflowPattern.DYNAMIC if model_driven else WorkflowPattern.GRAPH,
        node_path=("source_worker" if model_driven else "route_catalog",),
        attempt=1,
        isolation_scope="worker_private" if model_driven else "node_private",
        status=ObservationStatus.COMPLETE,
        model_driven=model_driven,
        model_calls=int(model_driven),
        payload_digest="sha256:" + "b" * 64,
        timestamp="2026-08-30T13:00:00Z",
        agent_id="source_analyst_jde" if model_driven else None,
    )


def test_accounting_is_contiguous_exact_and_budgeted():
    ledger = TraceAccountant(max_model_calls=2, max_node_executions=3)
    assert ledger.record(observation(1)).model_calls == 0
    assert ledger.record(observation(2, model_driven=True)).model_calls == 1
    assert ledger.record(observation(3, model_driven=True)).model_calls == 2
    with pytest.raises(TelemetryViolation, match="trace_node_budget"):
        ledger.record(
            NodeObservation(
                **{
                    **dataclass_values(observation(4, model_driven=True)),
                    "node_run_id": "nr_NODEEXECUTION0004",
                }
            )
        )


def dataclass_values(value: NodeObservation) -> dict[str, object]:
    return {field: getattr(value, field) for field in value.__dataclass_fields__}


def thaw(value):
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [thaw(item) for item in value]
    return value


def test_deterministic_work_cannot_claim_model_calls_and_sequence_fails_closed():
    with pytest.raises(TelemetryViolation, match="observation_model_call"):
        NodeObservation(
            **{
                **dataclass_values(observation(1)),
                "model_calls": 1,
            }
        )
    ledger = TraceAccountant()
    with pytest.raises(TelemetryViolation, match="trace_sequence"):
        ledger.record(observation(2))


def test_bridge_projects_digest_only_and_publishes_closed_document():
    class Sink:
        def __init__(self):
            self.events = []

        async def append(self, *, event):
            self.events.append(event)
            return 7

    sink = Sink()
    bridge = SanitizedEventBridge(sink=sink)
    item = observation(1, model_driven=True)
    document = bridge.project(item)
    assert document.payload["payload"] == {
        "payloadKind": "node_execution",
        "digest": item.payload_digest,
    }
    assert "content" not in document.payload
    assert document.payload["orchestration"]["modelCall"] is True
    ContractValidator(
        Path("contracts/v2/schemas/a2a-event.schema.json")
    ).validate(thaw(document.payload))
    assert asyncio.run(bridge.publish(item)) == 7
    assert sink.events == [document]
