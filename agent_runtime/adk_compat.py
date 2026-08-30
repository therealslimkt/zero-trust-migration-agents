"""Narrow, version-gated imports for the verified Google ADK surface."""

from __future__ import annotations

import dataclasses
import importlib
import importlib.metadata
import sys
from typing import Any


ADK_DISTRIBUTION = "google-adk"
ADK_VERSION = "2.7.1"
PYTHON_VERSION = (3, 12)


class AdkCompatibilityError(RuntimeError):
    """The process cannot safely construct the pinned ADK runtime."""


class AdkUnavailableError(AdkCompatibilityError):
    """The pinned ADK distribution is not installed."""


class AdkVersionError(AdkCompatibilityError):
    """The installed ADK version differs from the reviewed version."""


@dataclasses.dataclass(frozen=True)
class AdkSymbols:
    """Only the ADK 2.7.1 classes this milestone has verified."""

    App: type[Any]
    Runner: type[Any]


def require_python_312() -> None:
    """Fail closed outside the reviewed production interpreter."""

    if sys.version_info[:2] != PYTHON_VERSION:
        actual = ".".join(str(part) for part in sys.version_info[:2])
        raise AdkCompatibilityError(
            f"agent runtime requires CPython 3.12; found {actual}"
        )


def installed_adk_version() -> str:
    try:
        return importlib.metadata.version(ADK_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise AdkUnavailableError(
            "google-adk 2.7.1 is not installed; use requirements-agent-runtime.txt"
        ) from exc


def load_adk() -> AdkSymbols:
    """Load the exact reviewed ADK API without importing it at package import."""

    require_python_312()
    actual = installed_adk_version()
    if actual != ADK_VERSION:
        raise AdkVersionError(
            f"google-adk version must be {ADK_VERSION}; found {actual}"
        )
    try:
        app_module = importlib.import_module("google.adk.apps.app")
        runner_module = importlib.import_module("google.adk.runners")
        app = app_module.App
        runner = runner_module.Runner
    except (AttributeError, ImportError) as exc:
        raise AdkCompatibilityError("google-adk 2.7.1 public surface is unavailable") from exc
    if not isinstance(app, type) or not isinstance(runner, type):
        raise AdkCompatibilityError("google-adk 2.7.1 public surface is invalid")
    return AdkSymbols(App=app, Runner=runner)
