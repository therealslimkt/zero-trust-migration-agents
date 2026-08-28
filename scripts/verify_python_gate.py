#!/usr/bin/env python3
"""Run the authoritative local Python test gate in fail-closed order."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUITES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("full local suite", ("-m", "pytest", "-q", "tests")),
    ("M4 focused suite", ("-m", "pytest", "-q", "tests/cloud_runtime")),
)

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def run_gate(
    *,
    runner: Runner = subprocess.run,
    python: str = sys.executable,
    project_root: Path = PROJECT_ROOT,
) -> int:
    for index, (label, arguments) in enumerate(SUITES, start=1):
        print(f"=== Python gate {index}/{len(SUITES)}: {label} ===", flush=True)
        try:
            result = runner(
                [python, *arguments],
                cwd=project_root,
                check=False,
            )
        except OSError:
            print(f"PYTHON TEST GATE FAILED: could not start {label}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            print(
                f"PYTHON TEST GATE FAILED: {label} exited {result.returncode}; "
                "later suites were not run",
                file=sys.stderr,
            )
            return result.returncode if 0 < result.returncode < 256 else 1
        print(f"=== Passed: {label} ===", flush=True)

    print("PYTHON TEST GATE PASSED", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print("PYTHON TEST GATE FAILED: arguments are not accepted", file=sys.stderr)
        return 2
    return run_gate()


if __name__ == "__main__":
    raise SystemExit(main())
