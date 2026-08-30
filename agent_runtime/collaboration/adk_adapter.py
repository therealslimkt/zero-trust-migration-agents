"""Narrow adapter for the verified public google-adk 2.7.1 Agent surface.

Tagged source verification established that ``Agent.mode`` accepts ``chat``,
``task``, and ``single_turn``.  A task agent receives ``finish_task``; a
single-turn child is exposed to its coordinator under the child's own name.
No private ADK classes are imported here.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from .models import AgentMode, CollaborationViolation
from .planning import EligibleTeam
from .profiles import ATLAS_PROFILE


ADK_VERSION = "2.7.1"
INTAKE_AGENT_NAME = "source_intake"


@dataclasses.dataclass(frozen=True)
class AdkSchemaBundle:
    """Caller-owned Pydantic schema classes required by the ADK constructor."""

    intake_input: type[object]
    intake_output: type[object]
    specialist_input: type[object]
    specialist_output: type[object]

    def __post_init__(self) -> None:
        if not all(
            isinstance(schema, type)
            for schema in (
                self.intake_input,
                self.intake_output,
                self.specialist_input,
                self.specialist_output,
            )
        ):
            raise CollaborationViolation("adk_schema_type")


@dataclasses.dataclass(frozen=True)
class AdkDelegationSurface:
    agent_name: str
    mode: AgentMode
    coordinator_tool_name: str
    completion: str


def delegation_surfaces(team: EligibleTeam) -> tuple[AdkDelegationSurface, ...]:
    return (
        AdkDelegationSurface(
            agent_name=INTAKE_AGENT_NAME,
            mode=AgentMode.TASK,
            coordinator_tool_name=INTAKE_AGENT_NAME,
            completion="finish_task",
        ),
        *(
            AdkDelegationSurface(
                agent_name=profile.specialist_id,
                mode=AgentMode.SINGLE_TURN,
                coordinator_tool_name=profile.specialist_id,
                completion="structured_node_output",
            )
            for profile in team.profiles
        ),
    )


def build_adk_atlas_team(
    *,
    agent_constructor: Callable[..., object],
    team: EligibleTeam,
    schemas: AdkSchemaBundle,
    model: object,
) -> object:
    """Create fresh child instances using only public ``Agent`` parameters.

    The constructor is injected so importing this module never imports ADK or
    creates a model client.  Production passes ``google.adk.Agent`` after the
    existing compatibility gate has confirmed version 2.7.1.
    """

    if not callable(agent_constructor):
        raise CollaborationViolation("adk_agent_constructor")
    if not isinstance(team, EligibleTeam):
        raise CollaborationViolation("adk_team")
    if not isinstance(schemas, AdkSchemaBundle):
        raise CollaborationViolation("adk_schemas")
    if model is None:
        raise CollaborationViolation("adk_model")

    intake = agent_constructor(
        name=INTAKE_AGENT_NAME,
        model=model,
        mode=AgentMode.TASK.value,
        description="Collects only missing migration intent in the current session.",
        instruction="Collect missing typed intent and call finish_task; never approve execution.",
        input_schema=schemas.intake_input,
        output_schema=schemas.intake_output,
    )
    specialists = [
        agent_constructor(
            name=profile.specialist_id,
            model=model,
            mode=AgentMode.SINGLE_TURN.value,
            description=profile.description,
            instruction="Return only the typed specialist result; do not address the user.",
            input_schema=schemas.specialist_input,
            output_schema=schemas.specialist_output,
        )
        for profile in team.profiles
    ]
    children = [intake, *specialists]
    if len({id(child) for child in children}) != len(children):
        raise CollaborationViolation("shared_adk_agent_instance")
    return agent_constructor(
        name=ATLAS_PROFILE.specialist_id,
        model=model,
        mode=AgentMode.CHAT.value,
        description=ATLAS_PROFILE.description,
        instruction=(
            "Delegate only to the eligible typed children, collect every selected "
            "result, and be the final speaker. Never approve or execute a migration."
        ),
        sub_agents=children,
    )
