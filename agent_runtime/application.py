"""Side-effect-free composition boundary for the ADK fleet application."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from typing import Any

from .adk_compat import AdkSymbols, load_adk
from .ports import RuntimePorts


_APP_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_ENVIRONMENTS = frozenset({"development", "test", "staging", "production"})


@dataclasses.dataclass(frozen=True)
class RuntimeSettings:
    """Non-secret settings needed to assemble an ADK application."""

    app_name: str
    environment: str

    def __post_init__(self) -> None:
        if (
            type(self.app_name) is not str
            or _APP_NAME_RE.fullmatch(self.app_name) is None
            or self.app_name == "user"
        ):
            raise ValueError("runtime_app_name")
        if self.environment not in _ENVIRONMENTS:
            raise ValueError("runtime_environment")


@dataclasses.dataclass(frozen=True)
class RuntimeContext:
    """Explicit authority passed to the root agent/node factory."""

    settings: RuntimeSettings
    ports: RuntimePorts

    def __post_init__(self) -> None:
        if not isinstance(self.settings, RuntimeSettings):
            raise TypeError("runtime_settings")
        if not isinstance(self.ports, RuntimePorts):
            raise TypeError("runtime_ports")


@dataclasses.dataclass(frozen=True)
class RuntimeApplication:
    """An assembled ADK App paired with its explicit enterprise authority."""

    context: RuntimeContext
    adk_app: object = dataclasses.field(repr=False)
    _adk: AdkSymbols = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.context, RuntimeContext):
            raise TypeError("runtime_context")
        if not isinstance(self._adk, AdkSymbols):
            raise TypeError("runtime_adk_symbols")
        if self.adk_app is None:
            raise TypeError("runtime_adk_app")


RootFactory = Callable[[RuntimeContext], object]


def build_application(
    *,
    settings: RuntimeSettings,
    ports: RuntimePorts,
    root_factory: RootFactory,
) -> RuntimeApplication:
    """Construct an ADK App; never create credentials, services, or clients.

    ``root_factory`` receives the only authorities available to the fleet.  It
    must return an ADK ``BaseAgent`` or ``BaseNode``.  ADK's reviewed ``App``
    constructor performs that exact type check.
    """

    if not callable(root_factory):
        raise TypeError("runtime_root_factory")
    context = RuntimeContext(settings=settings, ports=ports)
    adk = load_adk()
    root = root_factory(context)
    app = adk.App(name=settings.app_name, root_agent=root)
    return RuntimeApplication(context=context, adk_app=app, _adk=adk)


def build_runner(
    application: RuntimeApplication,
    *,
    session_service: object,
    artifact_service: object | None = None,
    memory_service: object | None = None,
    credential_service: object | None = None,
) -> object:
    """Construct a production Runner from caller-provided ADK services.

    The function intentionally has no defaults for session persistence and
    never imports ADK in-memory services.  Calling it only constructs a Runner;
    execution begins later through ADK's asynchronous ``run_async`` API.
    """

    if not isinstance(application, RuntimeApplication):
        raise TypeError("runtime_application")
    if session_service is None:
        raise TypeError("runtime_session_service")
    return application._adk.Runner(
        app=application.adk_app,
        session_service=session_service,
        artifact_service=artifact_service,
        memory_service=memory_service,
        credential_service=credential_service,
        auto_create_session=False,
    )
