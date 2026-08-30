"""Least-authority adapter for ADK 2.7.1 dynamic node invocation."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any

from .types import (
    AgentInvocation,
    AgentResponse,
    SchemaOutputError,
    TransientInvocationError,
)


RunNode = Callable[..., Awaitable[Any]]
ResponseDecoder = Callable[[Any, AgentInvocation], AgentResponse]


class AdkTransientFailure(RuntimeError):
    """The injected ADK callable classified a failure as transient."""


class AdkSchemaFailure(RuntimeError):
    """The injected decoder rejected a closed output schema."""


class DynamicAdapterError(RuntimeError):
    """A sanitized, closed error emitted at the ADK adapter boundary."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _closed_response(value: Any, _invocation: AgentInvocation) -> AgentResponse:
    if not isinstance(value, AgentResponse):
        raise AdkSchemaFailure("adk_response_type")
    return value


@dataclasses.dataclass(frozen=True)
class ContextRunNodeAdapter:
    """Invoke one node through an injected, bound ADK ``Context.run_node``.

    The adapter was checked against the public google-adk 2.7.1 signature.  It
    directly awaits ``run_node`` (as ADK requires), forces a sub-branch and the
    scheduler-issued isolation scope, and carries no RuntimePorts, credentials,
    approval authority, executor, or signer.
    """

    run_node: RunNode = dataclasses.field(repr=False)
    node: object = dataclasses.field(repr=False)
    decode: ResponseDecoder = dataclasses.field(default=_closed_response, repr=False)

    def __post_init__(self) -> None:
        if not callable(self.run_node):
            raise TypeError("adk_run_node")
        if self.node is None:
            raise TypeError("adk_dynamic_node")
        if not callable(self.decode):
            raise TypeError("adk_response_decoder")

    async def invoke(self, invocation: AgentInvocation) -> AgentResponse:
        if not isinstance(invocation, AgentInvocation):
            raise TypeError("adk_invocation")
        try:
            value = await self.run_node(
                self.node,
                node_input=invocation,
                run_id=invocation.invocation_id,
                use_sub_branch=True,
                override_isolation_scope=invocation.isolation_scope,
                raise_on_wait=True,
            )
            response = self.decode(value, invocation)
            if not isinstance(response, AgentResponse):
                raise AdkSchemaFailure("adk_response_type")
            return response
        except asyncio.CancelledError:
            raise
        except AdkTransientFailure:
            raise TransientInvocationError("adk_transient_failure") from None
        except AdkSchemaFailure:
            raise SchemaOutputError("adk_schema_failure") from None
        except (TransientInvocationError, SchemaOutputError):
            raise
        except Exception:
            # Never copy provider, node, or decoder exception text across the
            # adapter boundary; it may contain protected request information.
            raise DynamicAdapterError("adk_invocation_failure") from None
