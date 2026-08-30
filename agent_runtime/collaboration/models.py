"""Immutable, provider-neutral contracts for Atlas collaboration.

These records deliberately carry no model client or ADK object.  They form the
validation boundary around whichever ADK 2.7.1 agents a composition root later
injects.
"""

from __future__ import annotations

import dataclasses
import enum
import re
from collections.abc import Sequence


_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.:-]{1,127}$")


class CollaborationViolation(ValueError):
    """A fail-closed collaboration contract violation with a stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require_id(value: str, code: str) -> None:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise CollaborationViolation(code)


def require_text(value: str, code: str, *, maximum: int = 2000) -> None:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise CollaborationViolation(code)


def require_unique(values: Sequence[object], code: str) -> None:
    if len(values) != len(set(values)):
        raise CollaborationViolation(code)


class SourceFamily(str, enum.Enum):
    SAP = "sap_ecc_maxdb"
    JDE = "jde_e1_ibmi"
    ORACLE = "oracle_ebs"
    COBOL = "zos_cobol"
    IBMI = "ibmi_native"
    SAGE = "sage_cre_zen"
    AX = "dynamics_ax"


class AgentMode(str, enum.Enum):
    CHAT = "chat"
    TASK = "task"
    SINGLE_TURN = "single_turn"


class SpecialistCapability(str, enum.Enum):
    INVENTORY_SOURCE = "inventory_source"
    PROFILE_SCHEMA = "profile_schema"
    PROPOSE_MAPPING = "propose_mapping"
    VALIDATE_PLAN = "validate_plan"
    EXPLAIN_FAILURE = "explain_failure"
    RECOMMEND_DRIVER = "recommend_driver"


@dataclasses.dataclass(frozen=True)
class SourceInstance:
    source_instance_id: str
    family: SourceFamily

    def __post_init__(self) -> None:
        require_id(self.source_instance_id, "source_instance_id")
        if not isinstance(self.family, SourceFamily):
            raise CollaborationViolation("source_family")


@dataclasses.dataclass(frozen=True)
class Portfolio:
    run_id: str
    session_id: str
    objective: str
    sources: tuple[SourceInstance, ...]

    def __post_init__(self) -> None:
        require_id(self.run_id, "run_id")
        require_id(self.session_id, "session_id")
        require_text(self.objective, "objective")
        if type(self.sources) is not tuple or not 1 <= len(self.sources) <= 7:
            raise CollaborationViolation("portfolio_size")
        if not all(isinstance(source, SourceInstance) for source in self.sources):
            raise CollaborationViolation("portfolio_source")
        require_unique(
            tuple(source.source_instance_id for source in self.sources),
            "duplicate_source_instance",
        )


@dataclasses.dataclass(frozen=True)
class SpecialistRequest:
    request_id: str
    run_id: str
    session_id: str
    specialist_id: str
    capability: SpecialistCapability
    source_instance_ids: tuple[str, ...]
    objective: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.request_id, "request_id"),
            (self.run_id, "request_run_id"),
            (self.session_id, "request_session_id"),
            (self.specialist_id, "request_specialist_id"),
        ):
            require_id(value, code)
        if not isinstance(self.capability, SpecialistCapability):
            raise CollaborationViolation("request_capability")
        if type(self.source_instance_ids) is not tuple or not self.source_instance_ids:
            raise CollaborationViolation("request_sources")
        for source_id in self.source_instance_ids:
            require_id(source_id, "request_source_id")
        require_unique(self.source_instance_ids, "duplicate_request_source")
        require_text(self.objective, "request_objective")


@dataclasses.dataclass(frozen=True)
class SpecialistResult:
    request_id: str
    run_id: str
    session_id: str
    specialist_id: str
    source_instance_ids: tuple[str, ...]
    findings: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, code in (
            (self.request_id, "result_request_id"),
            (self.run_id, "result_run_id"),
            (self.session_id, "result_session_id"),
            (self.specialist_id, "result_specialist_id"),
        ):
            require_id(value, code)
        if type(self.source_instance_ids) is not tuple or not self.source_instance_ids:
            raise CollaborationViolation("result_sources")
        for source_id in self.source_instance_ids:
            require_id(source_id, "result_source_id")
        require_unique(self.source_instance_ids, "duplicate_result_source")
        if type(self.findings) is not tuple or not self.findings:
            raise CollaborationViolation("result_findings")
        for finding in self.findings:
            require_text(finding, "result_finding")
        if type(self.evidence_refs) is not tuple:
            raise CollaborationViolation("result_evidence_refs")
        for evidence_ref in self.evidence_refs:
            require_text(evidence_ref, "result_evidence_ref", maximum=400)
        require_unique(self.evidence_refs, "duplicate_result_evidence")


@dataclasses.dataclass(frozen=True)
class AtlasFinal:
    """The only user-visible output of a completed collaboration turn."""

    speaker_id: str
    summary: str
    source_instance_ids: tuple[str, ...]
    contributing_specialist_ids: tuple[str, ...]
    result_request_ids: tuple[str, ...]
    final: bool = True

    def __post_init__(self) -> None:
        require_id(self.speaker_id, "final_speaker_id")
        require_text(self.summary, "final_summary")
        for values, code in (
            (self.source_instance_ids, "final_source_id"),
            (self.contributing_specialist_ids, "final_specialist_id"),
            (self.result_request_ids, "final_request_id"),
        ):
            if type(values) is not tuple or not values:
                raise CollaborationViolation(code)
            for value in values:
                require_id(value, code)
            require_unique(values, f"duplicate_{code}")
        if type(self.final) is not bool:
            raise CollaborationViolation("final_flag")


@dataclasses.dataclass(frozen=True)
class CollaborationUsage:
    """Exact successful product-agent calls made by one collaboration turn."""

    specialist_model_calls: int
    atlas_model_calls: int
    total_model_calls: int
    max_model_calls: int

    def __post_init__(self) -> None:
        for value, code in (
            (self.specialist_model_calls, "usage_specialist_model_calls"),
            (self.atlas_model_calls, "usage_atlas_model_calls"),
            (self.total_model_calls, "usage_total_model_calls"),
            (self.max_model_calls, "usage_max_model_calls"),
        ):
            if type(value) is not int or value < 0:
                raise CollaborationViolation(code)
        if self.atlas_model_calls != 1:
            raise CollaborationViolation("usage_atlas_model_calls")
        if self.total_model_calls != (
            self.specialist_model_calls + self.atlas_model_calls
        ):
            raise CollaborationViolation("usage_model_call_sum")
        if self.total_model_calls > self.max_model_calls:
            raise CollaborationViolation("usage_model_call_budget")


@dataclasses.dataclass(frozen=True)
class CollaborationOutcome:
    results: tuple[SpecialistResult, ...]
    final: AtlasFinal
    usage: CollaborationUsage

    def __post_init__(self) -> None:
        if type(self.results) is not tuple or not self.results or not all(
            isinstance(result, SpecialistResult) for result in self.results
        ):
            raise CollaborationViolation("outcome_results")
        if not isinstance(self.final, AtlasFinal):
            raise CollaborationViolation("outcome_final")
        if not isinstance(self.usage, CollaborationUsage):
            raise CollaborationViolation("outcome_usage")
        if self.usage.specialist_model_calls != len(self.results):
            raise CollaborationViolation("outcome_usage_results")
