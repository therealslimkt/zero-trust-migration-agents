"""Bounded task-mode intake state with same-session resume enforcement."""

from __future__ import annotations

import dataclasses
import enum

from .models import (
    CollaborationViolation,
    Portfolio,
    SourceInstance,
    require_id,
    require_text,
    require_unique,
)


MAX_INTAKE_ROUNDS = 3
_MISSING_FIELDS = ("objective", "sources")
_ROUND_LIMIT_CODE = "intake_round_limit"


class IntakeStatus(str, enum.Enum):
    WAITING = "waiting"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclasses.dataclass(frozen=True)
class IntakeDraft:
    objective: str | None = None
    sources: tuple[SourceInstance, ...] = ()

    def __post_init__(self) -> None:
        if self.objective is not None:
            if type(self.objective) is not str or len(self.objective) > 2000:
                raise CollaborationViolation("intake_objective")
        if type(self.sources) is not tuple or not all(
            isinstance(source, SourceInstance) for source in self.sources
        ):
            raise CollaborationViolation("intake_sources")
        if len(self.sources) > 7:
            raise CollaborationViolation("intake_sources")
        require_unique(
            tuple(source.source_instance_id for source in self.sources),
            "duplicate_intake_source",
        )


@dataclasses.dataclass(frozen=True)
class IntakeInterrupt:
    interrupt_id: str
    session_id: str
    missing_fields: tuple[str, ...]
    prompt: str

    def __post_init__(self) -> None:
        require_id(self.interrupt_id, "intake_interrupt_id")
        require_id(self.session_id, "intake_interrupt_session_id")
        if type(self.missing_fields) is not tuple or not self.missing_fields:
            raise CollaborationViolation("intake_missing_fields")
        require_unique(self.missing_fields, "duplicate_intake_missing_field")
        if any(field not in _MISSING_FIELDS for field in self.missing_fields):
            raise CollaborationViolation("intake_missing_field")
        if self.missing_fields != tuple(
            field for field in _MISSING_FIELDS if field in self.missing_fields
        ):
            raise CollaborationViolation("intake_missing_field_order")
        require_text(self.prompt, "intake_prompt", maximum=1000)


@dataclasses.dataclass(frozen=True)
class IntakeState:
    intake_id: str
    run_id: str
    session_id: str
    revision: int
    status: IntakeStatus
    draft: IntakeDraft
    interrupt: IntakeInterrupt | None = None
    intent: Portfolio | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        for value, code in (
            (self.intake_id, "intake_state_id"),
            (self.run_id, "intake_state_run_id"),
            (self.session_id, "intake_state_session_id"),
        ):
            require_id(value, code)
        if type(self.revision) is not int or not 0 <= self.revision <= MAX_INTAKE_ROUNDS:
            raise CollaborationViolation("intake_revision")
        if not isinstance(self.status, IntakeStatus):
            raise CollaborationViolation("intake_status")
        if not isinstance(self.draft, IntakeDraft):
            raise CollaborationViolation("intake_state_draft")
        missing = _missing_fields(self.draft)
        if self.status is IntakeStatus.WAITING:
            if (
                not missing
                or not isinstance(self.interrupt, IntakeInterrupt)
                or self.intent is not None
                or self.failure_code is not None
                or self.revision >= MAX_INTAKE_ROUNDS
            ):
                raise CollaborationViolation("intake_waiting_state")
            if self.interrupt.session_id != self.session_id:
                raise CollaborationViolation("intake_interrupt_session_binding")
            if self.interrupt.interrupt_id != f"{self.intake_id}:r{self.revision}":
                raise CollaborationViolation("intake_interrupt_id_binding")
            if self.interrupt.missing_fields != missing:
                raise CollaborationViolation("intake_missing_fields_binding")
            if self.interrupt.prompt != _prompt_for(missing):
                raise CollaborationViolation("intake_prompt_binding")
        elif self.status is IntakeStatus.COMPLETE:
            if (
                missing
                or self.interrupt is not None
                or not isinstance(self.intent, Portfolio)
                or self.failure_code is not None
            ):
                raise CollaborationViolation("intake_complete_state")
            if (
                self.intent.run_id != self.run_id
                or self.intent.session_id != self.session_id
                or self.intent.objective != self.draft.objective
                or self.intent.sources != self.draft.sources
            ):
                raise CollaborationViolation("intake_intent_binding")
        elif (
            self.interrupt is not None
            or self.intent is not None
            or self.failure_code != _ROUND_LIMIT_CODE
            or not missing
            or self.revision != MAX_INTAKE_ROUNDS
        ):
            raise CollaborationViolation("intake_failed_state")


@dataclasses.dataclass(frozen=True)
class IntakeResponse:
    interrupt_id: str
    session_id: str
    objective: str | None = None
    sources: tuple[SourceInstance, ...] | None = None

    def __post_init__(self) -> None:
        require_id(self.interrupt_id, "intake_response_interrupt_id")
        require_id(self.session_id, "intake_response_session_id")
        if self.objective is not None:
            if type(self.objective) is not str or len(self.objective) > 2000:
                raise CollaborationViolation("intake_response_objective")
        if self.sources is not None and (
            type(self.sources) is not tuple
            or not all(isinstance(source, SourceInstance) for source in self.sources)
            or len(self.sources) > 7
        ):
            raise CollaborationViolation("intake_response_sources")
        if self.sources is not None:
            require_unique(
                tuple(source.source_instance_id for source in self.sources),
                "duplicate_intake_response_source",
            )


def _missing_fields(draft: IntakeDraft) -> tuple[str, ...]:
    missing: list[str] = []
    if draft.objective is None or not draft.objective.strip():
        missing.append("objective")
    if not draft.sources:
        missing.append("sources")
    return tuple(missing)


def _prompt_for(missing: tuple[str, ...]) -> str:
    return f"Provide the missing migration intent fields: {', '.join(missing)}."


def _evaluate(
    *, intake_id: str, run_id: str, session_id: str, revision: int, draft: IntakeDraft
) -> IntakeState:
    missing = _missing_fields(draft)
    if missing:
        if revision >= MAX_INTAKE_ROUNDS:
            return IntakeState(
                intake_id=intake_id,
                run_id=run_id,
                session_id=session_id,
                revision=revision,
                status=IntakeStatus.FAILED,
                draft=draft,
                failure_code=_ROUND_LIMIT_CODE,
            )
        interrupt = IntakeInterrupt(
            interrupt_id=f"{intake_id}:r{revision}",
            session_id=session_id,
            missing_fields=missing,
            prompt=_prompt_for(missing),
        )
        return IntakeState(
            intake_id=intake_id,
            run_id=run_id,
            session_id=session_id,
            revision=revision,
            status=IntakeStatus.WAITING,
            draft=draft,
            interrupt=interrupt,
        )
    intent = Portfolio(
        run_id=run_id,
        session_id=session_id,
        objective=draft.objective,
        sources=draft.sources,
    )
    return IntakeState(
        intake_id=intake_id,
        run_id=run_id,
        session_id=session_id,
        revision=revision,
        status=IntakeStatus.COMPLETE,
        draft=draft,
        intent=intent,
    )


def start_intake(
    *,
    intake_id: str,
    run_id: str,
    session_id: str,
    draft: IntakeDraft = IntakeDraft(),
) -> IntakeState:
    for value, code in (
        (intake_id, "intake_id"),
        (run_id, "intake_run_id"),
        (session_id, "intake_session_id"),
    ):
        require_id(value, code)
    if not isinstance(draft, IntakeDraft):
        raise CollaborationViolation("intake_draft")
    return _evaluate(
        intake_id=intake_id,
        run_id=run_id,
        session_id=session_id,
        revision=0,
        draft=draft,
    )


def resume_intake(state: IntakeState, response: IntakeResponse) -> IntakeState:
    if not isinstance(state, IntakeState) or not isinstance(response, IntakeResponse):
        raise CollaborationViolation("intake_resume")
    if state.status is not IntakeStatus.WAITING or state.interrupt is None:
        raise CollaborationViolation("intake_not_waiting")
    if response.session_id != state.session_id:
        raise CollaborationViolation("intake_session_mismatch")
    if response.interrupt_id != state.interrupt.interrupt_id:
        raise CollaborationViolation("intake_interrupt_mismatch")
    draft = IntakeDraft(
        objective=(
            response.objective
            if response.objective is not None
            else state.draft.objective
        ),
        sources=response.sources if response.sources is not None else state.draft.sources,
    )
    return _evaluate(
        intake_id=state.intake_id,
        run_id=state.run_id,
        session_id=state.session_id,
        revision=state.revision + 1,
        draft=draft,
    )
