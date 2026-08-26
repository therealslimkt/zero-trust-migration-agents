"""Private source transport using Tailscale identity and MagicDNS."""

from __future__ import annotations

import ipaddress
import subprocess
from collections.abc import Callable, Sequence

from .types import SOURCE_SPECS, SourcePayload, SourceSpec


class SourceTransportError(RuntimeError):
    """Raised without raw command output to avoid leaking source content."""


Runner = Callable[..., subprocess.CompletedProcess]


class TailscaleSSHTransport:
    def __init__(
        self,
        *,
        user: str = "kohalloran",
        tailscale_binary: str = "tailscale",
        timeout_seconds: int = 30,
        max_bytes: int = 16 * 1024 * 1024,
        runner: Runner = subprocess.run,
    ) -> None:
        if not user or any(character.isspace() for character in user):
            raise ValueError("invalid SSH user")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.user = user
        self.tailscale_binary = tailscale_binary
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.runner = runner

    @staticmethod
    def _validate_spec(spec: SourceSpec) -> None:
        try:
            ipaddress.ip_address(spec.hostname)
        except ValueError:
            pass
        else:
            raise ValueError("source hostname must be a MagicDNS name, not an IP")
        expected = SOURCE_SPECS.get(spec.source_id)
        if expected is None or spec != expected:
            raise ValueError("source specification is not allowlisted")

    def _run(self, args: Sequence[str]) -> subprocess.CompletedProcess:
        try:
            return self.runner(
                list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceTransportError("private source command failed") from exc

    def read(self, spec: SourceSpec) -> SourcePayload:
        self._validate_spec(spec)
        ping = self._run(
            [
                self.tailscale_binary,
                "ping",
                "--c",
                "1",
                "--timeout",
                "5s",
                spec.hostname,
            ]
        )
        if ping.returncode != 0:
            raise SourceTransportError(f"MagicDNS source is unreachable: {spec.hostname}")

        result = self._run(
            [
                self.tailscale_binary,
                "ssh",
                f"{self.user}@{spec.hostname}",
                "head",
                "-c",
                str(self.max_bytes + 1),
                "--",
                spec.remote_path,
            ]
        )
        if result.returncode != 0:
            raise SourceTransportError(f"source export read failed: {spec.source_id}")
        if len(result.stdout) > self.max_bytes:
            raise SourceTransportError(f"source export exceeds limit: {spec.source_id}")
        if not result.stdout:
            raise SourceTransportError(f"source export is empty: {spec.source_id}")
        return SourcePayload(spec=spec, data=result.stdout)
