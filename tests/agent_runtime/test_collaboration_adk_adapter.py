from __future__ import annotations

import types
import unittest

from agent_runtime.collaboration import (
    ADK_VERSION,
    AdkSchemaBundle,
    AgentMode,
    CollaborationViolation,
    Portfolio,
    SourceFamily,
    SourceInstance,
    build_adk_atlas_team,
    build_eligible_team,
    delegation_surfaces,
)


class Schema:
    pass


class FakeAgentConstructor:
    def __init__(self, *, reuse=False):
        self.calls = []
        self.reuse = reuse
        self.shared = types.SimpleNamespace(name="shared")

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.reuse and kwargs["name"] != "atlas":
            return self.shared
        return types.SimpleNamespace(**kwargs)


def team():
    return build_eligible_team(
        Portfolio(
            run_id="run_adk",
            session_id="ses_adk",
            objective="Inspect sanitized JDE metadata.",
            sources=(
                SourceInstance(source_instance_id="src_jde", family=SourceFamily.JDE),
            ),
        ),
        permitted_advisor_ids=frozenset({"maven"}),
    )


class CollaborationAdkAdapterTests(unittest.TestCase):
    def test_adapter_records_exact_verified_271_delegation_surface(self):
        self.assertEqual(ADK_VERSION, "2.7.1")
        surfaces = delegation_surfaces(team())
        intake = surfaces[0]
        self.assertEqual(intake.mode, AgentMode.TASK)
        self.assertEqual(intake.coordinator_tool_name, "source_intake")
        self.assertEqual(intake.completion, "finish_task")
        for surface in surfaces[1:]:
            self.assertEqual(surface.mode, AgentMode.SINGLE_TURN)
            self.assertEqual(surface.coordinator_tool_name, surface.agent_name)
            self.assertEqual(surface.completion, "structured_node_output")
            self.assertFalse(surface.coordinator_tool_name.startswith("request_task_"))

    def test_public_constructor_builds_fresh_typed_children_and_chat_atlas(self):
        constructor = FakeAgentConstructor()
        schemas = AdkSchemaBundle(Schema, Schema, Schema, Schema)
        atlas = build_adk_atlas_team(
            agent_constructor=constructor,
            team=team(),
            schemas=schemas,
            model="injected-model",
        )
        self.assertEqual(atlas.name, "atlas")
        self.assertEqual(atlas.mode, "chat")
        children = atlas.sub_agents
        self.assertEqual(len(children), 3)
        self.assertEqual(children[0].name, "source_intake")
        self.assertEqual(children[0].mode, "task")
        self.assertTrue(
            all(
                child is not other
                for index, child in enumerate(children)
                for other in children[index + 1 :]
            )
        )
        self.assertEqual(
            {child.mode for child in children[1:]}, {"single_turn"}
        )
        self.assertIs(children[0].input_schema, Schema)

    def test_shared_child_instance_is_rejected(self):
        with self.assertRaisesRegex(CollaborationViolation, "shared_adk_agent_instance"):
            build_adk_atlas_team(
                agent_constructor=FakeAgentConstructor(reuse=True),
                team=team(),
                schemas=AdkSchemaBundle(Schema, Schema, Schema, Schema),
                model="injected-model",
            )


if __name__ == "__main__":
    unittest.main()
