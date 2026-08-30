from __future__ import annotations

import asyncio

import pytest

from agent_runtime.dynamic import (
    AdkSchemaFailure,
    AdkTransientFailure,
    AgentInvocation,
    AgentResponse,
    ContextRunNodeAdapter,
    DynamicAdapterError,
    SchemaOutputError,
    TransientInvocationError,
)
from agent_runtime.ports import ContractDocument


def invocation() -> AgentInvocation:
    return AgentInvocation(
        invocation_id="research_1",
        target="maven_research",
        isolation_scope="research/1",
        depth=0,
        attempt=1,
        repair_attempt=0,
        capabilities=("research", "sanitized_evidence_read"),
        request=ContractDocument("ztm.dynamic.request.v1", {"safe": True}),
    )


def response() -> AgentResponse:
    return AgentResponse(
        ContractDocument("ztm.dynamic.response.v1", {"status": "complete"})
    )


def run(coro):
    return asyncio.run(coro)


def test_context_adapter_uses_only_reviewed_isolated_run_node_arguments():
    calls = []
    node = object()

    async def run_node(*args, **kwargs):
        calls.append((args, kwargs))
        return {"closed": "output"}

    def decode(value, request):
        assert value == {"closed": "output"}
        assert request == invocation()
        return response()

    adapter = ContextRunNodeAdapter(run_node=run_node, node=node, decode=decode)
    result = run(adapter.invoke(invocation()))

    assert result == response()
    assert calls == [
        (
            (node,),
            {
                "node_input": invocation(),
                "run_id": "research_1",
                "use_sub_branch": True,
                "override_isolation_scope": "research/1",
                "raise_on_wait": True,
            },
        )
    ]
    assert set(vars(adapter)) == {"run_node", "node", "decode"}


@pytest.mark.parametrize(
    "external,mapped",
    [
        (AdkTransientFailure("provider secret"), TransientInvocationError),
        (AdkSchemaFailure("raw output"), SchemaOutputError),
    ],
)
def test_context_adapter_maps_typed_failures_without_external_detail(
    external, mapped
):
    async def run_node(*_args, **_kwargs):
        raise external

    adapter = ContextRunNodeAdapter(run_node=run_node, node=object())
    with pytest.raises(mapped) as caught:
        run(adapter.invoke(invocation()))

    assert "provider secret" not in str(caught.value)
    assert "raw output" not in str(caught.value)


def test_context_adapter_maps_unknown_failure_to_closed_code():
    async def run_node(*_args, **_kwargs):
        raise RuntimeError("customer row leaked by provider")

    adapter = ContextRunNodeAdapter(run_node=run_node, node=object())
    with pytest.raises(DynamicAdapterError) as caught:
        run(adapter.invoke(invocation()))

    assert caught.value.code == "adk_invocation_failure"
    assert "customer row" not in str(caught.value)


def test_context_adapter_rejects_unvalidated_response_as_schema_failure():
    async def run_node(*_args, **_kwargs):
        return {"not": "an AgentResponse"}

    adapter = ContextRunNodeAdapter(run_node=run_node, node=object())
    with pytest.raises(SchemaOutputError, match="adk_schema_failure"):
        run(adapter.invoke(invocation()))


def test_context_adapter_propagates_cancellation():
    async def run_node(*_args, **_kwargs):
        raise asyncio.CancelledError

    adapter = ContextRunNodeAdapter(run_node=run_node, node=object())
    with pytest.raises(asyncio.CancelledError):
        run(adapter.invoke(invocation()))
