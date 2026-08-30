from __future__ import annotations

import types
import unittest
from unittest import mock

from agent_runtime.adk_compat import AdkSymbols
from agent_runtime.application import (
    RuntimeApplication,
    RuntimeContext,
    RuntimeSettings,
    build_application,
    build_runner,
)

from .fakes import runtime_port_fakes


class FakeApp:
    def __init__(self, *, name, root_agent):
        self.name = name
        self.root_agent = root_agent


class FakeRunner:
    def __init__(self, **kwargs):
        self.arguments = kwargs


class RuntimeApplicationTests(unittest.TestCase):
    def test_build_application_injects_only_explicit_context(self):
        ports = runtime_port_fakes()
        settings = RuntimeSettings(
            app_name="zero-trust-migration-fleet", environment="test"
        )
        observed = []

        def root_factory(context):
            observed.append(context)
            return types.SimpleNamespace(name="root")

        symbols = AdkSymbols(App=FakeApp, Runner=FakeRunner)
        with mock.patch("agent_runtime.application.load_adk", return_value=symbols):
            application = build_application(
                settings=settings, ports=ports, root_factory=root_factory
            )

        self.assertIsInstance(application, RuntimeApplication)
        self.assertEqual(observed, [application.context])
        self.assertIs(application.context.ports, ports)
        self.assertEqual(application.adk_app.name, settings.app_name)

    def test_runner_requires_session_service_and_disables_auto_create(self):
        settings = RuntimeSettings(app_name="fleet", environment="test")
        context_ports = runtime_port_fakes()
        symbols = AdkSymbols(App=FakeApp, Runner=FakeRunner)
        application = RuntimeApplication(
            context=RuntimeContext(settings=settings, ports=context_ports),
            adk_app=FakeApp(name="fleet", root_agent=object()),
            _adk=symbols,
        )
        session_service = object()
        runner = build_runner(application, session_service=session_service)
        self.assertIs(runner.arguments["session_service"], session_service)
        self.assertFalse(runner.arguments["auto_create_session"])
        with self.assertRaisesRegex(TypeError, "runtime_session_service"):
            build_runner(application, session_service=None)

    def test_runtime_application_rejects_forged_context(self):
        symbols = AdkSymbols(App=FakeApp, Runner=FakeRunner)
        with self.assertRaisesRegex(TypeError, "runtime_context"):
            RuntimeApplication(context=object(), adk_app=object(), _adk=symbols)

    def test_settings_reject_invalid_or_reserved_names_and_unknown_environment(self):
        for name in ("", "2fleet", "user", "fleet space"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "runtime_app_name"):
                    RuntimeSettings(app_name=name, environment="test")
        with self.assertRaisesRegex(ValueError, "runtime_environment"):
            RuntimeSettings(app_name="fleet", environment="preview")


if __name__ == "__main__":
    unittest.main()
