"""Deterministic, bounded scheduling for source and Maven dynamic work."""

from __future__ import annotations

import asyncio
import dataclasses
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
class _UsageCounter:
    model_calls: int = 0
    logical_invocations: int = 0
    transient_retries: int = 0
    schema_repairs: int = 0


@dataclasses.dataclass
class _RunContext:
    runner: DynamicAgentRunner
    limits: DynamicLimits
    semaphore: asyncio.Semaphore
    budget: _CallBudget
    usage: _UsageCounter
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
    context.usage.logical_invocations += 1
    transient_retries = 0
    repair_attempt = 0
    attempt = 0
    next_call_kind: str | None = None
    while True:
        if not await context.budget.consume():
            return None, "agent_call_budget_exhausted"
        context.usage.model_calls += 1
        if next_call_kind == "transient":
            context.usage.transient_retries += 1
        elif next_call_kind == "schema":
            context.usage.schema_repairs += 1
        next_call_kind = None
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
            next_call_kind = "transient"
        except SchemaOutputError:
            if repair_attempt >= context.limits.max_schema_repairs:
                return None, "schema_repairs_exhausted"
            repair_attempt += 1
            next_call_kind = "schema"
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
    children = await _gather_structured(
        tuple(
            _research_branch(context, child, path + (child_index,))
            for child_index, child in enumerate(response.children)
        )
    )
    error = None if all(child.complete for child in children) else "child_incomplete"
    return BranchOutcome(path, scope, response, children=children, error_code=error)


async def _gather_structured(
    operations: Sequence[Awaitable[BranchOutcome]],
) -> Tuple[BranchOutcome, ...]:
    """Gather in declared order and never leave an unobserved sibling task."""

    tasks = tuple(asyncio.create_task(operation) for operation in operations)
    try:
        return tuple(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _branch_quotas(total: int, branch_count: int) -> Tuple[int, ...]:
    """Deterministically distribute the global budget round-robin by root.

    A root and all of its descendants share one quota.  No early flaky root
    can consume another root's first call, and the quota sum never exceeds the
    configured global ceiling.
    """

    quotient, remainder = divmod(total, branch_count)
    return tuple(
        quotient + (1 if index < remainder else 0)
        for index in range(branch_count)
    )


class DynamicWorkflowEngine:
    """Runs bounded branches without holding any privileged runtime port."""

    def __init__(
        self,
        *,
        runner: DynamicAgentRunner,
        limits: DynamicLimits = DynamicLimits(),
        sleep: Sleep = asyncio.sleep,
    ):
        if not isinstance(runner, DynamicAgentRunner):
            raise TypeError("dynamic_runner")
        if not isinstance(limits, DynamicLimits):
            raise TypeError("dynamic_limits")
        if not callable(sleep):
            raise TypeError("dynamic_sleep")
        self._runner = runner
        self._limits = limits
        self._sleep = sleep

    def _contexts(self, branch_count: int) -> Tuple[_RunContext, ...]:
        semaphore = asyncio.Semaphore(self._limits.max_concurrency)
        usage = _UsageCounter()
        return tuple(
            _RunContext(
                runner=self._runner,
                limits=self._limits,
                semaphore=semaphore,
                budget=_CallBudget(quota),
                usage=usage,
                sleep=self._sleep,
            )
            for quota in _branch_quotas(
                self._limits.max_agent_calls, branch_count
            )
        )

    async def _bounded_run(
        self,
        contexts: Sequence[_RunContext],
        operation: Awaitable[Tuple[BranchOutcome, ...]],
        started: float,
    ) -> DynamicRunResult:
        task = asyncio.create_task(operation)
        try:
            outcomes = await asyncio.wait_for(
                task, timeout=self._limits.wall_time_seconds
            )
        except asyncio.TimeoutError as exc:
            # wait_for cancels and awaits ``task`` on a genuine deadline.  An
            # inner TimeoutError leaves it completed rather than cancelled.
            if not task.cancelled():
                raise
            raise DynamicWorkflowTimedOut(
                self._usage(contexts, started)
            ) from exc
        result = DynamicRunResult(
            outcomes=outcomes,
            usage=self._usage(contexts, started),
        )
        if not all(outcome.complete for outcome in outcomes):
            raise DynamicWorkflowBlocked(result)
        return result

    @staticmethod
    def _usage(
        contexts: Sequence[_RunContext], started: float
    ) -> DynamicUsage:
        counter = contexts[0].usage
        # asyncio.wait_for and loop.time use the same event-loop clock.
        elapsed = max(0.0, asyncio.get_running_loop().time() - started)
        return DynamicUsage(
            model_calls=counter.model_calls,
            logical_invocations=counter.logical_invocations,
            transient_retries=counter.transient_retries,
            schema_repairs=counter.schema_repairs,
            elapsed_seconds=elapsed,
        )

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
        contexts = self._contexts(len(sources))
        started = asyncio.get_running_loop().time()
        operation = _gather_structured(
            tuple(
                _source_branch(contexts[index], source, index)
                for index, source in enumerate(sources)
            )
        )
        return await self._bounded_run(contexts, operation, started)

    async def run_maven_research(
        self, topics: Sequence[ResearchRequest]
    ) -> DynamicRunResult:
        """Run 3-7 top-level topics and recursively accept at most depth two."""

        _validate_width(topics, minimum=3, maximum=7, code="research_top_width")
        if any(not isinstance(topic, ResearchRequest) for topic in topics):
            raise DynamicValidationError("research_topic")
        _require_unique([topic.topic_id for topic in topics], "research_topic_duplicate")
        contexts = self._contexts(len(topics))
        started = asyncio.get_running_loop().time()
        operation = _gather_structured(
            tuple(
                _research_branch(contexts[index], topic, (index,))
                for index, topic in enumerate(topics)
            )
        )
        return await self._bounded_run(contexts, operation, started)
