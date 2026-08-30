#!/usr/bin/env python3
"""Run the offline v1 compatibility gate in deterministic fail-closed order."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Gate:
    label: str
    command: tuple[str, ...]
    cwd: Path
    environment: tuple[tuple[str, str], ...] = ()


Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def gates(*, project_root: Path = PROJECT_ROOT, python: str = sys.executable) -> tuple[Gate, ...]:
    """Return the single authoritative, non-deploying local gate order."""

    cache_root = Path(tempfile.gettempdir()) / "ztm-v1-baseline-cache"
    python_cache = (("PYTHONPYCACHEPREFIX", str(cache_root / "python")),)
    go_cache = (("GOCACHE", str(cache_root / "go")),)
    return (
        Gate(
            "frozen v1 compatibility invariants",
            (python, "-m", "unittest", "discover", "-s", "tests/baseline", "-v"),
            project_root,
            python_cache,
        ),
        Gate(
            "Python regression suites",
            (python, "-m", "scripts.verify_python_gate"),
            project_root,
            python_cache,
        ),
        Gate(
            "Go tests",
            ("go", "test", "./..."),
            project_root / "studio-backend",
            go_cache,
        ),
        Gate(
            "Go race tests",
            ("go", "test", "-race", "./..."),
            project_root / "studio-backend",
            go_cache,
        ),
        Gate(
            "Go vet",
            ("go", "vet", "./..."),
            project_root / "studio-backend",
            go_cache,
        ),
        Gate("frontend build", ("npm", "run", "build"), project_root / "studio"),
        Gate("frontend lint", ("npm", "run", "lint"), project_root / "studio"),
        Gate("frontend tests", ("npm", "test"), project_root / "studio"),
        Gate("whitespace errors", ("git", "diff", "--check"), project_root),
    )


def run_gate(
    *,
    runner: Runner = subprocess.run,
    project_root: Path = PROJECT_ROOT,
    python: str = sys.executable,
) -> int:
    selected = gates(project_root=project_root, python=python)
    for index, gate in enumerate(selected, start=1):
        print(
            f"=== v1 baseline {index}/{len(selected)}: {gate.label} ===",
            flush=True,
        )
        try:
            environment = os.environ.copy()
            environment.update(gate.environment)
            result = runner(
                list(gate.command),
                cwd=gate.cwd,
                check=False,
                env=environment,
            )
        except OSError:
            print(
                f"V1 BASELINE FAILED: could not start {gate.label}",
                file=sys.stderr,
            )
            return 1
        if result.returncode != 0:
            print(
                f"V1 BASELINE FAILED: {gate.label} exited {result.returncode}; "
                "later gates were not run",
                file=sys.stderr,
            )
            return result.returncode if 0 < result.returncode < 256 else 1
        print(f"=== Passed: {gate.label} ===", flush=True)

    print("V1 BASELINE PASSED", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print("V1 BASELINE FAILED: arguments are not accepted", file=sys.stderr)
        return 2
    return run_gate()


if __name__ == "__main__":
    raise SystemExit(main())
