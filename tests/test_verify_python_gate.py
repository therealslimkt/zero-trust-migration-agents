from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.verify_python_gate import SUITES, run_gate


class RecordingRunner:
    def __init__(self, returncodes: list[int]) -> None:
        self.returncodes = iter(returncodes)
        self.calls: list[tuple[list[str], Path, bool]] = []

    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((command, cwd, check))
        return subprocess.CompletedProcess(command, next(self.returncodes))


def test_gate_runs_full_then_focused_suite() -> None:
    runner = RecordingRunner([0, 0])
    root = Path("/safe/project")

    assert run_gate(runner=runner, python="/safe/python", project_root=root) == 0

    assert [call[0] for call in runner.calls] == [
        ["/safe/python", *arguments] for _, arguments in SUITES
    ]
    assert all(call[1] == root and call[2] is False for call in runner.calls)


def test_gate_stops_when_full_suite_fails() -> None:
    runner = RecordingRunner([3])

    assert run_gate(runner=runner) == 3
    assert len(runner.calls) == 1
    assert runner.calls[0][0][1:] == list(SUITES[0][1])


def test_gate_propagates_focused_suite_failure() -> None:
    runner = RecordingRunner([0, 5])

    assert run_gate(runner=runner) == 5
    assert len(runner.calls) == 2
