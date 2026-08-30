"""Bounded task-mode intake state with same-session resume enforcement."""

from __future__ import annotations

import dataclasses
import enum

from .models import (
    CollaborationViolation,
    Portfolio,
    SourceInstance,
    require_id,
)


class IntakeStatus(str, enum.Enum):
    WAITING = "waiting"
    COMPLETE = "complete"


@dataclasses.dataclass(frozen=True)
class IntakeDraft:
    objective: str | None = None
    sources: tuple[SourceInstance, ...] = ()

    def __post_init__(self) -> None:
        if self.objective is not None and type(self.objective) is not str:
            raise CollaborationViolation("intake_objective")
        if type(self.sources) is not tuple or not all(
            isinstance(source, SourceInstance) for source in self.sources
        ):
            raise CollaborationViolation("intake_sources")
        if len(self.sources) > 7:
            raise CollaborationViolation("intake_sources")


@dataclasses.dataclass(frozen=True)
class IntakeInterrupt:
    interrupt_id: str
    session_id: str
    missing_fields: tuple[str, ...]
    prompt: str


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


@dataclasses.dataclass(frozen=True)
class IntakeResponse:
    interrupt_id: str
    session_id: str
    objective: str | None = None
    sources: tuple[SourceInstance, ...] | None = None

    def __post_init__(self) -> None:
        require_id(self.interrupt_id, "intake_response_interrupt_id")
        require_id(self.session_id, "intake_response_session_id")
        if self.objective is not None and type(self.objective) is not str:
            raise CollaborationViolation("intake_response_objective")
        if self.sources is not None and (
            type(self.sources) is not tuple
            or not all(isinstance(source, SourceInstance) for source in self.sources)
            or len(self.sources) > 7
        ):
            raise CollaborationViolation("intake_response_sources")


def _evaluate(
    *, intake_id: str, run_id: str, session_id: str, revision: int, draft: IntakeDraft
) -> IntakeState:
    missing: list[str] = []
    if draft.objective is None or not draft.objective.strip():
        missing.append("objective")
    if not draft.sources:
        missing.append("sources")
    if missing:
        interrupt = IntakeInterrupt(
            interrupt_id=f"{intake_id}:r{revision}",
            session_id=session_id,
            missing_fields=tuple(missing),
            prompt=f"Provide the missing migration intent fields: {', '.join(missing)}.",
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
