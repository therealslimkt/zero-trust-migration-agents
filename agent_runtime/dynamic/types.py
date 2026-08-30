"""Closed internal types for bounded dynamic agent work.

These records are adapter SPI, not wire contracts.  Canonical documents cross
the boundary as :class:`ContractDocument` values after schema validation.  The
dynamic scheduler never receives an executor, approval authority, signing key,
or a capability that can read raw source data.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from typing import Optional, Protocol, Tuple, runtime_checkable

from agent_runtime.ports import ContractDocument


SOURCE_TARGET = "source_profiler"
RESEARCH_TARGET = "maven_research"
SOURCE_FAMILIES = frozenset(
    {
        "sap_ecc_maxdb",
        "jde_e1_ibmi",
        "oracle_ebs",
        "zos_cobol",
        "ibmi_native",
        "sage_cre_zen",
        "dynamics_ax",
    }
)
SOURCE_CAPABILITIES = ("sanitized_metadata_read", "source_profile")
RESEARCH_CAPABILITIES = ("research", "sanitized_evidence_read")
FORBIDDEN_CAPABILITIES = frozenset(
    {"execution", "approval", "signing", "raw_data", "raw_data_read"}
)

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class DynamicValidationError(ValueError):
    """A dynamic request violates a deterministic boundary rule."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TransientInvocationError(RuntimeError):
    """The adapter observed an allowlisted transient provider failure."""


class SchemaOutputError(RuntimeError):
    """The adapter rejected model output against its closed response schema."""


def _require_identifier(value: str, code: str) -> None:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise DynamicValidationError(code)


def _require_document(value: ContractDocument, code: str) -> None:
    if not isinstance(value, ContractDocument):
        raise DynamicValidationError(code)


def _require_capabilities(
    capabilities: Sequence[str], *, expected: Tuple[str, ...], code: str
) -> Tuple[str, ...]:
    if isinstance(capabilities, (str, bytes, bytearray)):
        raise DynamicValidationError(code)
    values = tuple(capabilities)
    if any(type(value) is not str for value in values):
        raise DynamicValidationError(code)
    if FORBIDDEN_CAPABILITIES.intersection(values) or values != expected:
        raise DynamicValidationError(code)
    return values


@dataclasses.dataclass(frozen=True)
class SourceInstance:
    """One catalog-selected source instance carrying sanitized metadata only."""

    instance_id: str
    source_id: str
    request: ContractDocument = dataclasses.field(repr=False)
    target: str = SOURCE_TARGET
    capabilities: Tuple[str, ...] = SOURCE_CAPABILITIES

    def __post_init__(self) -> None:
        _require_identifier(self.instance_id, "source_instance_id")
        _require_identifier(self.source_id, "source_id")
        if self.source_id not in SOURCE_FAMILIES:
            raise DynamicValidationError("source_family")
        _require_document(self.request, "source_request")
        if self.target != SOURCE_TARGET:
            raise DynamicValidationError("source_target")
        object.__setattr__(
            self,
            "capabilities",
            _require_capabilities(
                self.capabilities,
                expected=SOURCE_CAPABILITIES,
                code="source_capabilities",
            ),
        )


@dataclasses.dataclass(frozen=True)
class ResearchRequest:
    """One sanitized Maven research request, including recursive proposals."""

    topic_id: str
    request: ContractDocument = dataclasses.field(repr=False)
    target: str = RESEARCH_TARGET
    capabilities: Tuple[str, ...] = RESEARCH_CAPABILITIES

    def __post_init__(self) -> None:
        _require_identifier(self.topic_id, "research_topic_id")
        _require_document(self.request, "research_request")
        if self.target != RESEARCH_TARGET:
            raise DynamicValidationError("research_target")
        object.__setattr__(
            self,
            "capabilities",
            _require_capabilities(
                self.capabilities,
                expected=RESEARCH_CAPABILITIES,
                code="research_capabilities",
            ),
        )


@dataclasses.dataclass(frozen=True)
class AgentInvocation:
    """The complete, least-authority request visible to an injected runner."""

    invocation_id: str
    target: str
    isolation_scope: str
    depth: int
    attempt: int
    repair_attempt: int
    capabilities: Tuple[str, ...]
    request: ContractDocument = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.invocation_id, "invocation_id")
        if self.target not in (SOURCE_TARGET, RESEARCH_TARGET):
            raise DynamicValidationError("invocation_target")
        if type(self.isolation_scope) is not str or not self.isolation_scope:
            raise DynamicValidationError("isolation_scope")
        if type(self.depth) is not int or not 0 <= self.depth <= 2:
            raise DynamicValidationError("invocation_depth")
        if type(self.attempt) is not int or self.attempt < 1:
            raise DynamicValidationError("invocation_attempt")
        if type(self.repair_attempt) is not int or self.repair_attempt < 0:
            raise DynamicValidationError("repair_attempt")
        expected = (
            SOURCE_CAPABILITIES
            if self.target == SOURCE_TARGET
            else RESEARCH_CAPABILITIES
        )
        object.__setattr__(
            self,
            "capabilities",
            _require_capabilities(
                self.capabilities,
                expected=expected,
                code="invocation_capabilities",
            ),
        )
        _require_document(self.request, "invocation_request")


@dataclasses.dataclass(frozen=True)
class AgentResponse:
    """A schema-validated result and optional bounded research proposals."""

    output: ContractDocument = dataclasses.field(repr=False)
    complete: bool = True
    children: Tuple[ResearchRequest, ...] = ()

    def __post_init__(self) -> None:
        _require_document(self.output, "response_output")
        if type(self.complete) is not bool:
            raise DynamicValidationError("response_complete")
        if not isinstance(self.children, tuple) or any(
            not isinstance(child, ResearchRequest) for child in self.children
        ):
            raise DynamicValidationError("response_children")


@runtime_checkable
class DynamicAgentRunner(Protocol):
    """Narrow adapter over one ADK runner invocation.

    A production adapter may translate this record into the public ADK 2.7.1
    ``Runner.run_async`` call.  Scheduling remains here so that concurrency,
    recursion, and call budgets are independent of undocumented ADK internals.
    """

    async def invoke(self, invocation: AgentInvocation) -> AgentResponse: ...


@dataclasses.dataclass(frozen=True)
class DynamicLimits:
    """Per-run limits, each bounded by the reviewed production ceiling."""

    max_concurrency: int = 4
    max_agent_calls: int = 30
    wall_time_seconds: float = 180.0
    max_schema_repairs: int = 3
    max_transient_retries: int = 2
    retry_base_seconds: float = 0.25
    retry_max_seconds: float = 2.0

    def __post_init__(self) -> None:
        integer_bounds = (
            ("max_concurrency", self.max_concurrency, 1, 4),
            ("max_agent_calls", self.max_agent_calls, 1, 30),
            ("max_schema_repairs", self.max_schema_repairs, 0, 3),
            ("max_transient_retries", self.max_transient_retries, 0, 3),
        )
        for name, value, minimum, maximum in integer_bounds:
            if type(value) is not int or not minimum <= value <= maximum:
                raise DynamicValidationError(name)
        numeric_bounds = (
            ("wall_time_seconds", self.wall_time_seconds, 0.001, 180.0),
            ("retry_base_seconds", self.retry_base_seconds, 0.0, 10.0),
            ("retry_max_seconds", self.retry_max_seconds, 0.0, 10.0),
        )
        for name, value, minimum, maximum in numeric_bounds:
            if type(value) not in (int, float) or not minimum <= value <= maximum:
                raise DynamicValidationError(name)
        if self.retry_base_seconds > self.retry_max_seconds:
            raise DynamicValidationError("retry_backoff")


@dataclasses.dataclass(frozen=True)
class DynamicUsage:
    agent_calls: int
    elapsed_seconds: float


@dataclasses.dataclass(frozen=True)
class BranchOutcome:
    """One ordered branch outcome; failed children make their parent incomplete."""

    path: Tuple[int, ...]
    isolation_scope: str
    response: Optional[AgentResponse]
    children: Tuple["BranchOutcome", ...] = ()
    error_code: Optional[str] = None

    @property
    def complete(self) -> bool:
        return (
            self.error_code is None
            and self.response is not None
            and self.response.complete
            and all(child.complete for child in self.children)
        )


@dataclasses.dataclass(frozen=True)
class DynamicRunResult:
    outcomes: Tuple[BranchOutcome, ...]
    usage: DynamicUsage


class DynamicWorkflowBlocked(RuntimeError):
    """At least one branch was incomplete; no aggregate may be approved."""

    def __init__(self, result: DynamicRunResult):
        super().__init__("dynamic_workflow_incomplete")
        self.result = result


class DynamicWorkflowTimedOut(RuntimeError):
    """The wall-time bound expired and all live branches were cancelled."""

    def __init__(self, usage: DynamicUsage):
        super().__init__("dynamic_workflow_timeout")
        self.usage = usage
