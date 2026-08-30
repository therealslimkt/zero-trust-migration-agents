from __future__ import annotations

import types
import unittest
from unittest import mock

from agent_runtime import adk_compat


class AdkCompatibilityTests(unittest.TestCase):
    def test_python_runtime_is_exactly_312(self):
        with mock.patch.object(adk_compat.sys, "version_info", (3, 11, 9)):
            with self.assertRaisesRegex(adk_compat.AdkCompatibilityError, "CPython 3.12"):
                adk_compat.require_python_312()
        with mock.patch.object(adk_compat.sys, "version_info", (3, 12, 8)):
            adk_compat.require_python_312()

    def test_missing_or_wrong_adk_version_fails_before_import(self):
        with mock.patch.object(adk_compat.sys, "version_info", (3, 12, 1)), mock.patch.object(
            adk_compat.importlib.metadata,
            "version",
            side_effect=adk_compat.importlib.metadata.PackageNotFoundError,
        ), self.assertRaises(adk_compat.AdkUnavailableError):
            adk_compat.load_adk()

        with mock.patch.object(adk_compat.sys, "version_info", (3, 12, 1)), mock.patch.object(
            adk_compat.importlib.metadata, "version", return_value="2.8.0"
        ), mock.patch.object(adk_compat.importlib, "import_module") as importer:
            with self.assertRaisesRegex(adk_compat.AdkVersionError, "2.7.1"):
                adk_compat.load_adk()
            importer.assert_not_called()

    def test_only_verified_modules_are_imported(self):
        app_type = type("App", (), {})
        runner_type = type("Runner", (), {})
        modules = {
            "google.adk.apps.app": types.SimpleNamespace(App=app_type),
            "google.adk.runners": types.SimpleNamespace(Runner=runner_type),
        }
        with mock.patch.object(adk_compat.sys, "version_info", (3, 12, 1)), mock.patch.object(
            adk_compat.importlib.metadata, "version", return_value="2.7.1"
        ), mock.patch.object(
            adk_compat.importlib, "import_module", side_effect=modules.__getitem__
        ) as importer:
            symbols = adk_compat.load_adk()
        self.assertIs(symbols.App, app_type)
        self.assertIs(symbols.Runner, runner_type)
        self.assertEqual(
            [call.args[0] for call in importer.call_args_list],
            ["google.adk.apps.app", "google.adk.runners"],
        )

    def test_pattern_loader_uses_only_reviewed_public_modules(self):
        agent_type = type("Agent", (), {})
        workflow_type = type("Workflow", (), {})
        join_type = type("JoinNode", (), {})
        start = object()
        node_factory = lambda value: value
        modules = {
            "google.adk.agents": types.SimpleNamespace(Agent=agent_type),
            "google.adk.workflow": types.SimpleNamespace(
                Workflow=workflow_type,
                JoinNode=join_type,
                START=start,
                DEFAULT_ROUTE="__DEFAULT__",
                node=node_factory,
            ),
        }
        with mock.patch.object(
            adk_compat.sys, "version_info", (3, 12, 1)
        ), mock.patch.object(
            adk_compat.importlib.metadata, "version", return_value="2.7.1"
        ), mock.patch.object(
            adk_compat.importlib, "import_module", side_effect=modules.__getitem__
        ) as importer:
            symbols = adk_compat.load_adk_patterns()
        self.assertIs(symbols.Agent, agent_type)
        self.assertIs(symbols.Workflow, workflow_type)
        self.assertIs(symbols.JoinNode, join_type)
        self.assertIs(symbols.START, start)
        self.assertIs(symbols.node, node_factory)
        self.assertEqual(
            [call.args[0] for call in importer.call_args_list],
            ["google.adk.agents", "google.adk.workflow"],
        )


if __name__ == "__main__":
    unittest.main()
