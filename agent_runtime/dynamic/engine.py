"""Deterministic, bounded scheduling for source and Maven dynamic work."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Tuple

from .types import (
    AgentInvocation,
    AgentResponse,
    BranchOutcome,
    DynamicAgentRunner,
    DynamicLimits,
    DynamicRunResult,
    DynamicUsage,
    DynamicValidationError,
    DynamicWorkflowBlocked,
    DynamicWorkflowTimedOut,
    RESEARCH_TARGET,
    ResearchRequest,
    SOURCE_TARGET,
    SchemaOutputError,
    SourceInstance,
    TransientInvocationError,
)


Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class _CallBudget:
    def __init__(self, maximum: int):
        self._maximum = maximum
        self._used = 0
        self._lock = asyncio.Lock()

    @property
    def used(self) -> int:
        return self._used

    async def consume(self) -> bool:
        async with self._lock:
            if self._used >= self._maximum:
                return False
            self._used += 1
            return True


@dataclasses.dataclass
class _RunContext:
    runner: DynamicAgentRunner
    limits: DynamicLimits
    semaphore: asyncio.Semaphore
    budget: _CallBudget
    sleep: Sleep


def _validate_width(
    values: Sequence[object], *, minimum: int, maximum: int, code: str
) -> None:
    if not isinstance(values, Sequence) or isinstance(
        values, (str, bytes, bytearray)
    ) or not (
        minimum <= len(values) <= maximum
    ):
        raise DynamicValidationError(code)


def _require_unique(values: Sequence[str], code: str) -> None:
    if len(set(values)) != len(values):
        raise DynamicValidationError(code)


async def _invoke(
    context: _RunContext,
    invocation: AgentInvocation,
) -> Tuple[AgentResponse | None, str | None]:
    transient_retries = 0
    repair_attempt = 0
    attempt = 0
    while True:
        if not await context.budget.consume():
            return None, "agent_call_budget_exhausted"
        attempt += 1
        current = dataclasses.replace(
            invocation, attempt=attempt, repair_attempt=repair_attempt
        )
        try:
            async with context.semaphore:
                response = await context.runner.invoke(current)
            if not isinstance(response, AgentResponse):
                raise SchemaOutputError("response_type")
            return response, None
        except TransientInvocationError:
            if transient_retries >= context.limits.max_transient_retries:
                return None, "transient_retries_exhausted"
            delay = min(
                context.limits.retry_max_seconds,
                context.limits.retry_base_seconds * (2**transient_retries),
            )
            transient_retries += 1
            await context.sleep(delay)
        except SchemaOutputError:
            if repair_attempt >= context.limits.max_schema_repairs:
                return None, "schema_repairs_exhausted"
            repair_attempt += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            # Adapter exception text can contain provider or customer details.
            return None, "runner_failure"


async def _source_branch(
    context: _RunContext, source: SourceInstance, index: int
) -> BranchOutcome:
    scope = f"source/{source.instance_id}"
    invocation = AgentInvocation(
        invocation_id=f"source_{index + 1}",
        target=SOURCE_TARGET,
        isolation_scope=scope,
        depth=0,
        attempt=1,
        repair_attempt=0,
        capabilities=source.capabilities,
        request=source.request,
    )
    response, error = await _invoke(context, invocation)
    if response is not None and response.children:
        return BranchOutcome((index,), scope, response, error_code="source_recursion")
    if response is not None and not response.complete:
        error = "incomplete_output"
    return BranchOutcome((index,), scope, response, error_code=error)


async def _research_branch(
    context: _RunContext,
    request: ResearchRequest,
    path: Tuple[int, ...],
) -> BranchOutcome:
    depth = len(path) - 1
    scope = "research/" + "/".join(str(index + 1) for index in path)
    invocation = AgentInvocation(
        invocation_id="research_" + "_".join(str(index + 1) for index in path),
        target=RESEARCH_TARGET,
        isolation_scope=scope,
        depth=depth,
        attempt=1,
        repair_attempt=0,
        capabilities=request.capabilities,
        request=request.request,
    )
    response, error = await _invoke(context, invocation)
    if response is None:
        return BranchOutcome(path, scope, None, error_code=error)
    if not response.complete:
        return BranchOutcome(path, scope, response, error_code="incomplete_output")
    if len(response.children) > 3:
        return BranchOutcome(path, scope, response, error_code="research_child_width")
    if depth == 2 and response.children:
        return BranchOutcome(path, scope, response, error_code="research_max_depth")
    children = tuple(
        await asyncio.gather(
            *(
                _research_branch(context, child, path + (child_index,))
                for child_index, child in enumerate(response.children)
            )
        )
    )
    error = None if all(child.complete for child in children) else "child_incomplete"
    return BranchOutcome(path, scope, response, children=children, error_code=error)


class DynamicWorkflowEngine:
    """Runs bounded branches without holding any privileged runtime port."""

    def __init__(
        self,
        *,
        runner: DynamicAgentRunner,
        limits: DynamicLimits = DynamicLimits(),
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ):
        if not isinstance(runner, DynamicAgentRunner):
            raise TypeError("dynamic_runner")
        if not isinstance(limits, DynamicLimits):
            raise TypeError("dynamic_limits")
        if not callable(sleep) or not callable(clock):
            raise TypeError("dynamic_clock")
        self._runner = runner
        self._limits = limits
        self._sleep = sleep
        self._clock = clock

    def _context(self) -> _RunContext:
        return _RunContext(
            runner=self._runner,
            limits=self._limits,
            semaphore=asyncio.Semaphore(self._limits.max_concurrency),
            budget=_CallBudget(self._limits.max_agent_calls),
            sleep=self._sleep,
        )

    async def _bounded_run(
        self,
        context: _RunContext,
        operation: Awaitable[Tuple[BranchOutcome, ...]],
        started: float,
    ) -> DynamicRunResult:
        try:
            outcomes = await asyncio.wait_for(
                operation, timeout=self._limits.wall_time_seconds
            )
        except asyncio.TimeoutError as exc:
            usage = DynamicUsage(
                agent_calls=context.budget.used,
                elapsed_seconds=max(0.0, self._clock() - started),
            )
            raise DynamicWorkflowTimedOut(usage) from exc
        result = DynamicRunResult(
            outcomes=outcomes,
            usage=DynamicUsage(
                agent_calls=context.budget.used,
                elapsed_seconds=max(0.0, self._clock() - started),
            ),
        )
        if not all(outcome.complete for outcome in outcomes):
            raise DynamicWorkflowBlocked(result)
        return result

    async def run_source_fanout(
        self, sources: Sequence[SourceInstance]
    ) -> DynamicRunResult:
        """Profile 1-7 sources concurrently and preserve declared order."""

        _validate_width(sources, minimum=1, maximum=7, code="source_width")
        if any(not isinstance(source, SourceInstance) for source in sources):
            raise DynamicValidationError("source_instance")
        _require_unique(
            [source.instance_id for source in sources], "source_instance_duplicate"
        )
        context = self._context()
        started = self._clock()
        operation = asyncio.gather(
            *(
                _source_branch(context, source, index)
                for index, source in enumerate(sources)
            )
        )
        return await self._bounded_run(context, operation, started)

    async def run_maven_research(
        self, topics: Sequence[ResearchRequest]
    ) -> DynamicRunResult:
        """Run 3-7 top-level topics and recursively accept at most depth two."""

        _validate_width(topics, minimum=3, maximum=7, code="research_top_width")
        if any(not isinstance(topic, ResearchRequest) for topic in topics):
            raise DynamicValidationError("research_topic")
        _require_unique([topic.topic_id for topic in topics], "research_topic_duplicate")
        context = self._context()
        started = self._clock()
        operation = asyncio.gather(
            *(
                _research_branch(context, topic, (index,))
                for index, topic in enumerate(topics)
            )
        )
        return await self._bounded_run(context, operation, started)
