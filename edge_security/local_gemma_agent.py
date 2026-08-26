"""Residual-PII verification by Gemma running locally on the Sparky edge node."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from collections.abc import Callable, Sequence
from typing import Optional

from edge_security.pii_redactor import PII_CATEGORIES, SanitizedSource


class LocalGemmaError(RuntimeError):
    """Fail-closed Gemma error that never includes model or candidate output."""


Runner = Callable[..., subprocess.CompletedProcess]


@dataclasses.dataclass(frozen=True)
class ResidualFinding:
    field: str
    category: str


@dataclasses.dataclass(frozen=True)
class LocalGemmaReview:
    status: str
    findings: tuple[ResidualFinding, ...]
    evidence_digest: str
    model: str = "gemma-2-2b"
    execution_location: str = "edge-local"

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def category_counts(self) -> dict[str, int]:
        counts = {category: 0 for category in PII_CATEGORIES}
        for finding in self.findings:
            counts[finding.category] += 1
        return counts


class TailscaleGemmaReviewer:
    """Send only deterministic output to a local Ollama Gemma over MagicDNS."""

    _SYSTEM_INSTRUCTION = (
        "You are a residual PII verifier. The candidate was deterministically "
        "protected. A value whose protection is tokenized and whose value starts "
        "with tok_ is safe, regardless of its field name. Record IDs, source IDs, "
        "record-set names, ordinals, and field names are safe metadata. Inspect "
        "only values whose protection is sanitized; do not infer a finding from "
        "semantic names such as account_balance. Never repeat any candidate value. "
        "Return only compact JSON "
        'with exactly {"status":"passed","findings":[]} when no residual PII '
        "is present, or status blocked and findings containing only field and "
        "category. Allowed categories: name, email, phone, address, "
        "governmentId, financialAccount, other."
    )

    def __init__(
        self,
        *,
        hostname: str = "sparky-sid-411116",
        user: str = "ohallaatme",
        tailscale_binary: str = "tailscale",
        ollama_model: str = "gemma2:2b",
        timeout_seconds: int = 120,
        max_candidate_bytes: int = 512 * 1024,
        max_response_bytes: int = 64 * 1024,
        runner: Runner = subprocess.run,
    ) -> None:
        if hostname != "sparky-sid-411116":
            raise ValueError("Gemma host must use the allowlisted MagicDNS name")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.hostname = hostname
        self.user = user
        self.tailscale_binary = tailscale_binary
        self.ollama_model = ollama_model
        self.timeout_seconds = timeout_seconds
        self.max_candidate_bytes = max_candidate_bytes
        self.max_response_bytes = max_response_bytes
        self.runner = runner

    def _run(self, args: Sequence[str], *, input_bytes: Optional[bytes] = None):
        try:
            return self.runner(
                list(args),
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LocalGemmaError("edge-local Gemma command failed") from exc

    @staticmethod
    def _candidate_fields(candidate: dict[str, object]) -> set[str]:
        fields = set()
        for record in candidate["records"]:
            for value in record["values"]:
                fields.add(value["field"])
        return fields

    def review(self, sanitized: SanitizedSource) -> LocalGemmaReview:
        candidate = sanitized.as_candidate()
        candidate_json = json.dumps(
            candidate,
            sort_keys=True,
            separators=(",", ":"),
        )
        prompt = (self._SYSTEM_INSTRUCTION + "\nCANDIDATE=" + candidate_json).encode(
            "utf-8"
        )
        if len(prompt) > self.max_candidate_bytes:
            raise LocalGemmaError("sanitized candidate exceeds local review limit")

        ping = self._run(
            [
                self.tailscale_binary,
                "ping",
                "--c",
                "1",
                "--timeout",
                "5s",
                "--until-direct=false",
                self.hostname,
            ]
        )
        if ping.returncode != 0:
            raise LocalGemmaError("edge-local Gemma host is unreachable")

        result = self._run(
            [
                self.tailscale_binary,
                "ssh",
                f"{self.user}@{self.hostname}",
                "env",
                "OLLAMA_NOHISTORY=1",
                "ollama",
                "run",
                self.ollama_model,
                "--format",
                "json",
                "--nowordwrap",
            ],
            input_bytes=prompt,
        )
        if result.returncode != 0 or len(result.stdout) > self.max_response_bytes:
            raise LocalGemmaError("edge-local Gemma review failed")

        try:
            verdict = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LocalGemmaError("edge-local Gemma returned an invalid verdict") from None
        if not isinstance(verdict, dict) or set(verdict) != {"status", "findings"}:
            raise LocalGemmaError("edge-local Gemma returned an invalid verdict")
        if verdict["status"] not in {"passed", "blocked"} or not isinstance(
            verdict["findings"], list
        ):
            raise LocalGemmaError("edge-local Gemma returned an invalid verdict")
        if verdict["status"] == "passed" and verdict["findings"]:
            raise LocalGemmaError("edge-local Gemma returned an inconsistent verdict")
        if verdict["status"] == "blocked" and not verdict["findings"]:
            raise LocalGemmaError("edge-local Gemma returned an inconsistent verdict")

        allowed_fields = self._candidate_fields(candidate)
        findings = []
        for item in verdict["findings"]:
            if not isinstance(item, dict) or set(item) != {"field", "category"}:
                raise LocalGemmaError("edge-local Gemma returned an invalid finding")
            if item["field"] not in allowed_fields or item["category"] not in PII_CATEGORIES:
                raise LocalGemmaError("edge-local Gemma returned an invalid finding")
            findings.append(ResidualFinding(item["field"], item["category"]))

        return LocalGemmaReview(
            status=verdict["status"],
            findings=tuple(findings),
            evidence_digest="sha256:" + hashlib.sha256(result.stdout).hexdigest(),
        )
