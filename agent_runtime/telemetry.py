"""Exact model-call accounting and sanitized Mission Control projection."""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import re

from .ports import ContractDocument, EventSink


MAX_MODEL_CALLS = 30
MAX_NODE_EXECUTIONS = 100
A2A_EVENT_SCHEMA_ID = (
    "https://zero-trust-migration.example/contracts/v2/2.0.0/"
    "a2a-event.schema.json"
)

_NODE_ID = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
_NODE_RUN_ID = re.compile(r"^nr_[A-Za-z0-9]{12,64}$")
_TASK_ID = re.compile(r"^task_[A-Za-z0-9]{8,64}$")
_TRACE_ID = re.compile(r"^[a-f0-9]{32}$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)


class TelemetryViolation(ValueError):
    """A trace could not be projected without weakening its contract."""


class WorkflowPattern(str, enum.Enum):
    GRAPH = "graph"
    COLLABORATIVE = "collaborative"
    DYNAMIC = "dynamic"


class ObservationStatus(str, enum.Enum):
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ISOLATION_SCOPES = frozenset(
    {
        "shared_readonly",
        "node_private",
        "worker_private",
        "session_private",
        "tenant_private",
    }
)


@dataclasses.dataclass(frozen=True)
class NodeObservation:
    """One node attempt; a model-driven attempt crosses exactly one boundary."""

    sequence: int
    node_run_id: str
    task_id: str
    trace_id: str
    pattern: WorkflowPattern
    node_path: tuple[str, ...]
    attempt: int
    isolation_scope: str
    status: ObservationStatus
    model_driven: bool
    model_calls: int
    payload_digest: str
    timestamp: str
    agent_id: str | None = None
    parent_node_run_id: str | None = None
    route: str | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise TelemetryViolation("observation_sequence")
        if type(self.attempt) is not int or self.attempt < 1:
            raise TelemetryViolation("observation_attempt")
        if not _NODE_RUN_ID.fullmatch(self.node_run_id):
            raise TelemetryViolation("observation_node_run_id")
        if not _TASK_ID.fullmatch(self.task_id):
            raise TelemetryViolation("observation_task_id")
        if not _TRACE_ID.fullmatch(self.trace_id):
            raise TelemetryViolation("observation_trace_id")
        if not isinstance(self.pattern, WorkflowPattern):
            raise TelemetryViolation("observation_pattern")
        if not 1 <= len(self.node_path) <= 16 or any(
            type(item) is not str or _NODE_ID.fullmatch(item) is None
            for item in self.node_path
        ):
            raise TelemetryViolation("observation_node_path")
        if self.isolation_scope not in _ISOLATION_SCOPES:
            raise TelemetryViolation("observation_isolation_scope")
        if not isinstance(self.status, ObservationStatus):
            raise TelemetryViolation("observation_status")
        if type(self.model_driven) is not bool or type(self.model_calls) is not int:
            raise TelemetryViolation("observation_model_call")
        if self.model_calls not in (0, 1) or self.model_driven != (self.model_calls == 1):
            raise TelemetryViolation("observation_model_call")
        if self.model_driven and not self.agent_id:
            raise TelemetryViolation("observation_agent")
        if self.parent_node_run_id is not None and not _NODE_RUN_ID.fullmatch(
            self.parent_node_run_id
        ):
            raise TelemetryViolation("observation_parent")
        if not _DIGEST.fullmatch(self.payload_digest):
            raise TelemetryViolation("observation_digest")
        if type(self.timestamp) is not str or not _TIMESTAMP.fullmatch(self.timestamp):
            raise TelemetryViolation("observation_timestamp")
        if self.route is not None and (
            type(self.route) is not str or not self.route or len(self.route) > 64
        ):
            raise TelemetryViolation("observation_route")


@dataclasses.dataclass(frozen=True)
class TraceUsage:
    node_executions: int
    model_calls: int


class TraceAccountant:
    """Append-only accounting shared by graph, team, and dynamic adapters."""

    def __init__(
        self,
        *,
        max_model_calls: int = MAX_MODEL_CALLS,
        max_node_executions: int = MAX_NODE_EXECUTIONS,
    ) -> None:
        if (
            type(max_model_calls) is not int
            or not 1 <= max_model_calls <= MAX_MODEL_CALLS
            or type(max_node_executions) is not int
            or not 1 <= max_node_executions <= MAX_NODE_EXECUTIONS
        ):
            raise TelemetryViolation("trace_budget")
        self._max_model_calls = max_model_calls
        self._max_node_executions = max_node_executions
        self._observations: list[NodeObservation] = []
        self._node_run_ids: set[str] = set()

    @property
    def observations(self) -> tuple[NodeObservation, ...]:
        return tuple(self._observations)

    @property
    def usage(self) -> TraceUsage:
        return TraceUsage(
            node_executions=len(self._observations),
            model_calls=sum(item.model_calls for item in self._observations),
        )

    def record(self, observation: NodeObservation) -> TraceUsage:
        if not isinstance(observation, NodeObservation):
            raise TelemetryViolation("trace_observation")
        if observation.sequence != len(self._observations) + 1:
            raise TelemetryViolation("trace_sequence")
        if observation.node_run_id in self._node_run_ids:
            raise TelemetryViolation("trace_node_run_duplicate")
        next_usage = TraceUsage(
            node_executions=len(self._observations) + 1,
            model_calls=self.usage.model_calls + observation.model_calls,
        )
        if next_usage.node_executions > self._max_node_executions:
            raise TelemetryViolation("trace_node_budget")
        if next_usage.model_calls > self._max_model_calls:
            raise TelemetryViolation("trace_model_budget")
        self._observations.append(observation)
        self._node_run_ids.add(observation.node_run_id)
        return next_usage


class SanitizedEventBridge:
    """Publish only closed metadata and a content digest, never node content."""

    def __init__(self, *, sink: EventSink) -> None:
        if not isinstance(sink, EventSink):
            raise TypeError("event_bridge_sink")
        self._sink = sink

    @staticmethod
    def project(observation: NodeObservation) -> ContractDocument:
        if not isinstance(observation, NodeObservation):
            raise TelemetryViolation("event_observation")
        stable = (
            f"{observation.trace_id}:{observation.task_id}:"
            f"{observation.node_run_id}:{observation.sequence}"
        )
        event_id = "evt_" + hashlib.sha256(stable.encode()).hexdigest()[:24]
        orchestration: dict[str, object] = {
            "pattern": observation.pattern.value,
            "nodePath": observation.node_path,
            "nodeRunId": observation.node_run_id,
            "attempt": observation.attempt,
            "isolationScope": observation.isolation_scope,
            "modelCall": observation.model_driven,
        }
        if observation.parent_node_run_id is not None:
            orchestration["parentNodeRunId"] = observation.parent_node_run_id
        if observation.route is not None:
            orchestration["route"] = observation.route
        node_id = observation.node_path[-1]
        payload = {
            "schemaVersion": "2.0.0",
            "eventId": event_id,
            "traceId": observation.trace_id,
            "taskId": observation.task_id,
            "from": observation.agent_id or "atlas",
            "to": "mission_control",
            "type": f"orchestration.node_{observation.status.value}",
            "sequence": observation.sequence,
            "timestamp": observation.timestamp,
            "summary": f"{node_id} {observation.status.value}",
            "contextRefs": (),
            "artifactRefs": (),
            "status": observation.status.value,
            "requiresHumanApproval": False,
            "payload": {
                "payloadKind": "node_execution",
                "digest": observation.payload_digest,
            },
            "orchestration": orchestration,
        }
        return ContractDocument(A2A_EVENT_SCHEMA_ID, payload)

    async def publish(self, observation: NodeObservation) -> int:
        return await self._sink.append(event=self.project(observation))
