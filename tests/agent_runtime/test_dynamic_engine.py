from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from agent_runtime.dynamic import (
    AgentInvocation,
    AgentResponse,
    DynamicLimits,
    DynamicValidationError,
    DynamicWorkflowBlocked,
    DynamicWorkflowEngine,
    DynamicWorkflowTimedOut,
    ResearchRequest,
    SchemaOutputError,
    SourceInstance,
    TransientInvocationError,
)
from agent_runtime.ports import ContractDocument


Behavior = Callable[[AgentInvocation], Awaitable[AgentResponse]]


def document(name: str, value: str = "safe") -> ContractDocument:
    return ContractDocument(f"ztm.dynamic.{name}.v1", {"value": value})


def source(index: int) -> SourceInstance:
    families = (
        "sap_ecc_maxdb",
        "jde_e1_ibmi",
        "oracle_ebs",
        "zos_cobol",
        "ibmi_native",
        "sage_cre_zen",
        "dynamics_ax",
    )
    return SourceInstance(
        instance_id=f"instance_{index}",
        source_id=families[index % len(families)],
        request=document("source-request", str(index)),
    )


def topic(index: int) -> ResearchRequest:
    return ResearchRequest(
        topic_id=f"topic_{index}", request=document("research-request", str(index))
    )


def response(invocation: AgentInvocation, *, children=(), complete=True):
    return AgentResponse(
        output=document("response", invocation.invocation_id),
        complete=complete,
        children=tuple(children),
    )


class RecordingRunner:
    def __init__(self, behavior: Behavior | None = None):
        self.behavior = behavior or self._success
        self.invocations: list[AgentInvocation] = []
        self.active = 0
        self.max_active = 0

    async def _success(self, invocation: AgentInvocation) -> AgentResponse:
        return response(invocation)

    async def invoke(self, invocation: AgentInvocation) -> AgentResponse:
        self.invocations.append(invocation)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            return await self.behavior(invocation)
        finally:
            self.active -= 1


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("width", [1, 7])
def test_source_fanout_accepts_boundary_widths_and_isolates_instances(width):
    runner = RecordingRunner()
    result = run(
        DynamicWorkflowEngine(runner=runner).run_source_fanout(
            [source(index) for index in range(width)]
        )
    )

    assert len(result.outcomes) == width
    assert result.usage.agent_calls == width
    assert [item.path for item in result.outcomes] == [(index,) for index in range(width)]
    assert [call.isolation_scope for call in runner.invocations] == [
        f"source/instance_{index}" for index in range(width)
    ]
    assert len({call.isolation_scope for call in runner.invocations}) == width
    assert all(
        call.capabilities == ("sanitized_metadata_read", "source_profile")
        for call in runner.invocations
    )


@pytest.mark.parametrize("width", [0, 8])
def test_source_fanout_rejects_out_of_range_width(width):
    with pytest.raises(DynamicValidationError, match="source_width"):
        run(
            DynamicWorkflowEngine(runner=RecordingRunner()).run_source_fanout(
                [source(index) for index in range(width)]
            )
        )


def test_source_fanout_rejects_duplicate_instance_scope():
    repeated = source(1)
    with pytest.raises(DynamicValidationError, match="source_instance_duplicate"):
        run(
            DynamicWorkflowEngine(runner=RecordingRunner()).run_source_fanout(
                [repeated, repeated]
            )
        )


def test_source_fanout_rejects_family_outside_frozen_cartridge_catalog():
    with pytest.raises(DynamicValidationError, match="source_family"):
        SourceInstance(
            instance_id="unknown_instance",
            source_id="unknown_legacy_system",
            request=document("unknown"),
        )


def test_global_concurrency_is_four_and_results_keep_input_order():
    release = asyncio.Event()
    reached_four = asyncio.Event()

    async def gated(invocation):
        if runner.active == 4:
            reached_four.set()
        await reached_four.wait()
        release.set()
        await release.wait()
        # Deliberately perturb completion order after the first scheduling wave.
        await asyncio.sleep((8 - int(invocation.invocation_id.split("_")[-1])) / 10000)
        return response(invocation)

    runner = RecordingRunner(gated)
    result = run(
        DynamicWorkflowEngine(runner=runner).run_source_fanout(
            [source(index) for index in range(7)]
        )
    )

    assert runner.max_active == 4
    assert [outcome.path for outcome in result.outcomes] == [
        (index,) for index in range(7)
    ]
    assert [outcome.response.output.payload["value"] for outcome in result.outcomes] == [
        f"source_{index + 1}" for index in range(7)
    ]


def test_transient_retry_recovers_with_bounded_exponential_backoff():
    failures = 2
    sleeps: list[float] = []

    async def flaky(invocation):
        nonlocal failures
        if failures:
            failures -= 1
            raise TransientInvocationError("provider detail is not surfaced")
        return response(invocation)

    async def record_sleep(delay):
        sleeps.append(delay)

    runner = RecordingRunner(flaky)
    result = run(
        DynamicWorkflowEngine(runner=runner, sleep=record_sleep).run_source_fanout(
            [source(0)]
        )
    )

    assert result.usage.agent_calls == 3
    assert [call.attempt for call in runner.invocations] == [1, 2, 3]
    assert sleeps == [0.25, 0.5]


def test_transient_retry_exhaustion_blocks_aggregate():
    async def unavailable(_invocation):
        raise TransientInvocationError("secret provider detail")

    runner = RecordingRunner(unavailable)
    with pytest.raises(DynamicWorkflowBlocked) as caught:
        run(
            DynamicWorkflowEngine(runner=runner, sleep=_no_sleep).run_source_fanout(
                [source(0)]
            )
        )

    assert caught.value.result.usage.agent_calls == 3
    assert caught.value.result.outcomes[0].error_code == "transient_retries_exhausted"
    assert "secret provider detail" not in repr(caught.value)


async def _no_sleep(_delay):
    return None


def test_three_schema_repairs_allow_success_on_fourth_call():
    invalid = 3

    async def repairing(invocation):
        nonlocal invalid
        if invalid:
            invalid -= 1
            raise SchemaOutputError("closed schema rejection")
        return response(invocation)

    runner = RecordingRunner(repairing)
    result = run(
        DynamicWorkflowEngine(runner=runner).run_source_fanout([source(0)])
    )

    assert result.usage.agent_calls == 4
    assert [call.repair_attempt for call in runner.invocations] == [0, 1, 2, 3]


def test_schema_repair_exhaustion_blocks_aggregate():
    async def malformed(_invocation):
        raise SchemaOutputError("bad output")

    with pytest.raises(DynamicWorkflowBlocked) as caught:
        run(
            DynamicWorkflowEngine(runner=RecordingRunner(malformed)).run_source_fanout(
                [source(0)]
            )
        )

    assert caught.value.result.usage.agent_calls == 4
    assert caught.value.result.outcomes[0].error_code == "schema_repairs_exhausted"


@pytest.mark.parametrize("width", [3, 7])
def test_maven_research_accepts_top_level_boundary_widths(width):
    runner = RecordingRunner()
    result = run(
        DynamicWorkflowEngine(runner=runner).run_maven_research(
            [topic(index) for index in range(width)]
        )
    )

    assert len(result.outcomes) == width
    assert [call.depth for call in runner.invocations] == [0] * width
    assert [call.isolation_scope for call in runner.invocations] == [
        f"research/{index + 1}" for index in range(width)
    ]


@pytest.mark.parametrize("width", [0, 2, 8])
def test_maven_research_rejects_top_level_out_of_range_width(width):
    with pytest.raises(DynamicValidationError, match="research_top_width"):
        run(
            DynamicWorkflowEngine(runner=RecordingRunner()).run_maven_research(
                [topic(index) for index in range(width)]
            )
        )


def test_maven_research_small_tree_has_deterministic_depth_and_order():
    async def expand(invocation):
        children = ()
        if invocation.depth < 2:
            children = (
                ResearchRequest(
                    topic_id=f"child_{invocation.depth}",
                    request=document("research-child", invocation.invocation_id),
                ),
            )
        return response(invocation, children=children)

    runner = RecordingRunner(expand)
    result = run(
        DynamicWorkflowEngine(runner=runner).run_maven_research(
            [topic(index) for index in range(3)]
        )
    )

    assert result.usage.agent_calls == 9
    for root_index, outcome in enumerate(result.outcomes, start=1):
        assert outcome.path == (root_index - 1,)
        assert outcome.children[0].path == (root_index - 1, 0)
        assert outcome.children[0].children[0].path == (root_index - 1, 0, 0)
        assert outcome.children[0].children[0].isolation_scope == f"research/{root_index}/1/1"
    assert sorted(call.depth for call in runner.invocations) == [0] * 3 + [1] * 3 + [2] * 3


def test_research_child_width_above_three_blocks_without_scheduling_children():
    async def too_wide(invocation):
        children = tuple(
            ResearchRequest(
                topic_id=f"child_{index}", request=document("child", str(index))
            )
            for index in range(4)
        )
        return response(invocation, children=children)

    runner = RecordingRunner(too_wide)
    with pytest.raises(DynamicWorkflowBlocked) as caught:
        run(
            DynamicWorkflowEngine(runner=runner).run_maven_research(
                [topic(index) for index in range(3)]
            )
        )

    assert len(runner.invocations) == 3
    assert [item.error_code for item in caught.value.result.outcomes] == [
        "research_child_width"
    ] * 3


def test_research_depth_above_two_blocks_without_invoking_depth_three():
    async def always_expand(invocation):
        return response(
            invocation,
            children=(
                ResearchRequest(
                    topic_id=f"child_{invocation.depth}",
                    request=document("child", invocation.invocation_id),
                ),
            ),
        )

    runner = RecordingRunner(always_expand)
    with pytest.raises(DynamicWorkflowBlocked) as caught:
        run(
            DynamicWorkflowEngine(runner=runner).run_maven_research(
                [topic(index) for index in range(3)]
            )
        )

    assert len(runner.invocations) == 9
    assert max(call.depth for call in runner.invocations) == 2
    assert all(root.error_code == "child_incomplete" for root in caught.value.result.outcomes)
    assert all(
        root.children[0].children[0].error_code == "research_max_depth"
        for root in caught.value.result.outcomes
    )


def test_agent_call_budget_blocks_incomplete_research_tree_at_thirty():
    async def expand(invocation):
        children = ()
        if invocation.depth < 2:
            children = tuple(
                ResearchRequest(
                    topic_id=f"child_{invocation.depth}_{index}",
                    request=document("child", f"{invocation.invocation_id}-{index}"),
                )
                for index in range(3)
            )
        return response(invocation, children=children)

    runner = RecordingRunner(expand)
    with pytest.raises(DynamicWorkflowBlocked) as caught:
        run(
            DynamicWorkflowEngine(runner=runner).run_maven_research(
                [topic(index) for index in range(3)]
            )
        )

    assert caught.value.result.usage.agent_calls == 30
    assert len(runner.invocations) == 30
    assert not all(root.complete for root in caught.value.result.outcomes)


def test_incomplete_branch_blocks_aggregate_while_siblings_remain_observable():
    async def incomplete_second(invocation):
        return response(invocation, complete=invocation.invocation_id != "source_2")

    runner = RecordingRunner(incomplete_second)
    with pytest.raises(DynamicWorkflowBlocked) as caught:
        run(
            DynamicWorkflowEngine(runner=runner).run_source_fanout(
                [source(index) for index in range(3)]
            )
        )

    assert [outcome.complete for outcome in caught.value.result.outcomes] == [
        True,
        False,
        True,
    ]
    assert caught.value.result.outcomes[1].error_code == "incomplete_output"


def test_wall_timeout_cancels_live_branches():
    cancelled = 0

    async def never_finishes(_invocation):
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled += 1

    runner = RecordingRunner(never_finishes)
    limits = DynamicLimits(wall_time_seconds=0.01)
    with pytest.raises(DynamicWorkflowTimedOut) as caught:
        run(
            DynamicWorkflowEngine(runner=runner, limits=limits).run_source_fanout(
                [source(index) for index in range(4)]
            )
        )

    assert caught.value.usage.agent_calls == 4
    assert cancelled == 4


@pytest.mark.parametrize("target", ["executor", "approval", "signer", "raw_data_reader"])
def test_forbidden_research_recursion_targets_fail_closed(target):
    with pytest.raises(DynamicValidationError, match="research_target"):
        ResearchRequest(
            topic_id="unsafe_topic",
            request=document("unsafe"),
            target=target,
        )


@pytest.mark.parametrize("capability", ["execution", "approval", "signing", "raw_data"])
def test_forbidden_research_capabilities_fail_closed(capability):
    with pytest.raises(DynamicValidationError, match="research_capabilities"):
        ResearchRequest(
            topic_id="unsafe_topic",
            request=document("unsafe"),
            capabilities=("research", "sanitized_evidence_read", capability),
        )


def test_source_response_cannot_create_recursive_workers():
    async def recursive(invocation):
        return response(invocation, children=(topic(0),))

    with pytest.raises(DynamicWorkflowBlocked) as caught:
        run(
            DynamicWorkflowEngine(runner=RecordingRunner(recursive)).run_source_fanout(
                [source(0)]
            )
        )

    assert caught.value.result.outcomes[0].error_code == "source_recursion"


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"max_concurrency": 5}, "max_concurrency"),
        ({"max_agent_calls": 31}, "max_agent_calls"),
        ({"wall_time_seconds": 181}, "wall_time_seconds"),
        ({"max_schema_repairs": 4}, "max_schema_repairs"),
    ],
)
def test_production_ceilings_cannot_be_configured_away(kwargs, code):
    with pytest.raises(DynamicValidationError, match=code):
        DynamicLimits(**kwargs)
