from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from scripts.verify_v1_baseline import gates, run_gate


class RecordingRunner:
    def __init__(self, returncodes: list[int] | None = None, fail_to_start: bool = False) -> None:
        self.returncodes = iter(returncodes or [])
        self.fail_to_start = fail_to_start
        self.calls: list[tuple[list[str], Path, bool, dict[str, str]]] = []

    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((command, cwd, check, env))
        if self.fail_to_start:
            raise OSError("unavailable")
        return subprocess.CompletedProcess(command, next(self.returncodes))


class VerifyV1BaselineTest(unittest.TestCase):
    def test_gate_order_is_explicit_and_uses_no_shell(self) -> None:
        root = Path("/safe/project")
        expected = gates(project_root=root, python="/safe/python")
        runner = RecordingRunner([0] * len(expected))

        self.assertEqual(
            run_gate(runner=runner, project_root=root, python="/safe/python"),
            0,
        )
        self.assertEqual(
            [call[0] for call in runner.calls],
            [list(gate.command) for gate in expected],
        )
        self.assertEqual(
            [call[1] for call in runner.calls],
            [gate.cwd for gate in expected],
        )
        self.assertTrue(all(call[2] is False for call in runner.calls))
        for call, gate in zip(runner.calls, expected):
            self.assertEqual(
                {name: call[3][name] for name, _ in gate.environment},
                dict(gate.environment),
            )

    def test_gate_stops_at_first_failure_and_propagates_normal_code(self) -> None:
        runner = RecordingRunner([0, 7])

        self.assertEqual(run_gate(runner=runner), 7)
        self.assertEqual(len(runner.calls), 2)

    def test_gate_normalizes_abnormal_return_code(self) -> None:
        runner = RecordingRunner([-9])

        self.assertEqual(run_gate(runner=runner), 1)
        self.assertEqual(len(runner.calls), 1)

    def test_gate_fails_closed_when_command_cannot_start(self) -> None:
        runner = RecordingRunner(fail_to_start=True)

        self.assertEqual(run_gate(runner=runner), 1)
        self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
