"""Concurrent specialist fan-out, validated fan-in, and Atlas-only synthesis."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Protocol, cast, runtime_checkable

from .models import (
    AtlasFinal,
    CollaborationOutcome,
    CollaborationUsage,
    CollaborationViolation,
    SpecialistRequest,
    SpecialistResult,
)
from .planning import AtlasDispatchPlan
from .profiles import ATLAS_ID


MAX_COLLABORATION_CONCURRENCY = 4
MAX_COLLABORATION_MODEL_CALLS = 30
MAX_COLLABORATION_WALL_SECONDS = 1800.0


@runtime_checkable
class SpecialistDispatcher(Protocol):
    async def dispatch(self, request: SpecialistRequest) -> SpecialistResult: ...


@dataclasses.dataclass(frozen=True)
class SynthesisInput:
    plan: AtlasDispatchPlan
    results: tuple[SpecialistResult, ...]


@runtime_checkable
class AtlasSynthesizer(Protocol):
    async def synthesize(self, synthesis_input: SynthesisInput) -> AtlasFinal: ...


def validate_results(
    plan: AtlasDispatchPlan, results: tuple[SpecialistResult, ...]
) -> tuple[SpecialistResult, ...]:
    """Validate exact request coverage and return deterministic request order."""

    expected = {request.request_id: request for request in plan.requests}
    observed: dict[str, SpecialistResult] = {}
    for result in results:
        if not isinstance(result, SpecialistResult):
            raise CollaborationViolation("invalid_specialist_result")
        if result.request_id in observed:
            raise CollaborationViolation("duplicate_specialist_result")
        request = expected.get(result.request_id)
        if request is None:
            raise CollaborationViolation("unauthorized_specialist_result")
        if result.run_id != request.run_id or result.session_id != request.session_id:
            raise CollaborationViolation("result_context_mismatch")
        if result.specialist_id != request.specialist_id:
            raise CollaborationViolation("result_specialist_mismatch")
        if result.source_instance_ids != request.source_instance_ids:
            raise CollaborationViolation("result_source_mismatch")
        observed[result.request_id] = result
    if set(observed) != set(expected):
        raise CollaborationViolation("missing_specialist_result")
    return tuple(observed[request.request_id] for request in plan.requests)


def validate_atlas_final(
    plan: AtlasDispatchPlan,
    results: tuple[SpecialistResult, ...],
    final: AtlasFinal,
) -> None:
    if not isinstance(final, AtlasFinal):
        raise CollaborationViolation("invalid_atlas_final")
    if final.speaker_id != ATLAS_ID or final.final is not True:
        raise CollaborationViolation("atlas_final_speaker")
    expected_sources = tuple(
        source.source_instance_id for source in plan.team.portfolio.sources
    )
    if set(final.source_instance_ids) != set(expected_sources):
        raise CollaborationViolation("atlas_final_source_coverage")
    if set(final.contributing_specialist_ids) != set(
        plan.selected_specialist_ids
    ):
        raise CollaborationViolation("atlas_final_contributors")
    if set(final.result_request_ids) != {result.request_id for result in results}:
        raise CollaborationViolation("atlas_final_results")


async def run_collaboration(
    plan: AtlasDispatchPlan,
    *,
    dispatcher: SpecialistDispatcher,
    synthesizer: AtlasSynthesizer,
    max_concurrency: int = 4,
    max_model_calls: int = 30,
    max_wall_clock_seconds: float = 1800.0,
) -> CollaborationOutcome:
    """Run a bounded turn, cancelling and awaiting every sibling on failure."""

    if not isinstance(plan, AtlasDispatchPlan):
        raise CollaborationViolation("collaboration_plan")
    if not isinstance(dispatcher, SpecialistDispatcher):
        raise CollaborationViolation("specialist_dispatcher")
    if not isinstance(synthesizer, AtlasSynthesizer):
        raise CollaborationViolation("atlas_synthesizer")
    if (
        type(max_concurrency) is not int
        or not 1 <= max_concurrency <= MAX_COLLABORATION_CONCURRENCY
    ):
        raise CollaborationViolation("collaboration_concurrency")
    if (
        type(max_model_calls) is not int
        or not 1 <= max_model_calls <= MAX_COLLABORATION_MODEL_CALLS
    ):
        raise CollaborationViolation("collaboration_model_call_limit")
    if (
        type(max_wall_clock_seconds) not in (int, float)
        or not 0 < max_wall_clock_seconds <= MAX_COLLABORATION_WALL_SECONDS
    ):
        raise CollaborationViolation("collaboration_wall_clock_limit")
    required_model_calls = len(plan.requests) + 1
    if required_model_calls > max_model_calls:
        raise CollaborationViolation("collaboration_model_call_budget")
    semaphore = asyncio.Semaphore(max_concurrency)
    raw_results: list[SpecialistResult | None] = [None] * len(plan.requests)

    async def dispatch_one(index: int, request: SpecialistRequest) -> None:
        async with semaphore:
            raw_results[index] = await dispatcher.dispatch(request)

    async with asyncio.timeout(max_wall_clock_seconds):
        async with asyncio.TaskGroup() as tasks:
            for index, request in enumerate(plan.requests):
                tasks.create_task(dispatch_one(index, request))
        results = validate_results(
            plan, cast(tuple[SpecialistResult, ...], tuple(raw_results))
        )
        final = await synthesizer.synthesize(
            SynthesisInput(plan=plan, results=results)
        )
    validate_atlas_final(plan, results, final)
    return CollaborationOutcome(
        results=results,
        final=final,
        usage=CollaborationUsage(
            specialist_model_calls=len(plan.requests),
            atlas_model_calls=1,
            total_model_calls=required_model_calls,
            max_model_calls=max_model_calls,
        ),
    )
