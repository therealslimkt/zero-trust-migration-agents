"""Optional no-network smoke test against the installed ADK 2.7.1 package."""

from __future__ import annotations

import unittest

from agent_runtime.adk_compat import AdkCompatibilityError, load_adk
from agent_runtime.application import RuntimeSettings, build_application, build_runner

from .fakes import runtime_port_fakes


try:
    _ADK = load_adk()
    _ADK_SKIP_REASON = ""
except AdkCompatibilityError as exc:
    _ADK = None
    _ADK_SKIP_REASON = str(exc)


@unittest.skipIf(_ADK is None, _ADK_SKIP_REASON)
class InstalledAdkSmokeTests(unittest.TestCase):
    def test_verified_app_and_runner_surface_constructs_without_network(self):
        from google.adk.agents.base_agent import BaseAgent
        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        class NoopAgent(BaseAgent):
            async def _run_async_impl(self, ctx):
                if False:
                    yield None

        application = build_application(
            settings=RuntimeSettings(app_name="fleet_smoke", environment="test"),
            ports=runtime_port_fakes(),
            root_factory=lambda context: NoopAgent(name="root"),
        )
        runner = build_runner(
            application, session_service=InMemorySessionService()
        )
        self.assertEqual(application.adk_app.name, "fleet_smoke")
        self.assertIs(runner.app, application.adk_app)
        self.assertFalse(runner.auto_create_session)


if __name__ == "__main__":
    unittest.main()
