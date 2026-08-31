#!/usr/bin/env python3
"""Loopback-only local agent for one sealed synthetic-cartridge evidence run.

It exposes no command, image, database, path, or shell argument to a browser.
The only mutation is invoking the repository's fixed, preflighted local Docker
evidence helper.  It is intentionally unavailable from hosted deployments.
"""

from __future__ import annotations

import hmac
import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_local_cartridge_evidence.sh"
HOST = "127.0.0.1"
PORT = 4344
SCHEMA = "keraun.cartridge-evidence/v1"
EXPECTED_CHECKS = frozenset(("jdeInvalidCyyddd", "axOrphanDerived", "ebsUnmappedFlexfield"))


class LocalAgentError(ValueError):
    """Fixed-vocabulary local-agent refusal."""


def require_token(value: str | None) -> str:
    if value is None or len(value) < 32 or any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
        raise LocalAgentError("local_agent_token")
    return value


def sanitize_evidence(raw: str) -> dict[str, Any]:
    """Accept exactly the known count-only evidence contract, never Docker logs."""

    candidate: dict[str, Any] | None = None
    for line in raw.splitlines():
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            candidate = decoded
    if candidate is None or set(candidate) != {"schemaVersion", "synthetic", "checks"}:
        raise LocalAgentError("evidence_shape")
    checks = candidate["checks"]
    if candidate["schemaVersion"] != SCHEMA or candidate["synthetic"] is not True or not isinstance(checks, dict):
        raise LocalAgentError("evidence_shape")
    if set(checks) != EXPECTED_CHECKS or any(type(value) is not int or value < 0 or value > 1_000 for value in checks.values()):
        raise LocalAgentError("evidence_shape")
    return {"schemaVersion": SCHEMA, "synthetic": True, "checks": {key: checks[key] for key in sorted(checks)}}


@dataclass
class EvidenceRun:
    status: str = "idle"
    request_id: str | None = None
    result: dict[str, Any] | None = None
    code: str | None = None

    def response(self) -> dict[str, Any]:
        response: dict[str, Any] = {"schemaVersion": "keraun.local-cartridge-agent/v1", "status": self.status}
        if self.request_id:
            response["requestId"] = self.request_id
        if self.result:
            response["evidence"] = self.result
        if self.code:
            response["code"] = self.code
        return response


class AgentState:
    def __init__(self, token: str):
        self.token = token
        self.lock = threading.Lock()
        self.run = EvidenceRun()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self.run.response()

    def start(self) -> tuple[dict[str, Any], bool]:
        with self.lock:
            if self.run.status == "running":
                return self.run.response(), False
            self.run = EvidenceRun(status="running", request_id=f"local_cartridge_{uuid.uuid4().hex}")
            response = self.run.response()
        threading.Thread(target=self._execute, daemon=True).start()
        return response, True

    def _execute(self) -> None:
        try:
            completed = subprocess.run(
                (str(RUNNER),), cwd=ROOT, check=False, text=True,
                capture_output=True, timeout=240,
            )
            if completed.returncode != 0:
                raise LocalAgentError("runner_failed")
            evidence = sanitize_evidence(completed.stdout)
        except Exception:  # Fail closed; no subprocess or Docker detail reaches the browser.
            with self.lock:
                self.run.status = "failed"
                self.run.code = "runner_failed"
            return
        with self.lock:
            self.run.status = "succeeded"
            self.run.result = evidence
            self.run.code = None


def handler_for(state: AgentState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied, f"Bearer {state.token}")

        def send_json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/v1/evidence-runs/current" or not self.authorized():
                self.send_json(HTTPStatus.NOT_FOUND, {"code": "not_found"})
                return
            self.send_json(HTTPStatus.OK, state.snapshot())

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/evidence-runs" or not self.authorized():
                self.send_json(HTTPStatus.NOT_FOUND, {"code": "not_found"})
                return
            if self.headers.get("Content-Length", "0") not in ("", "0"):
                self.send_json(HTTPStatus.BAD_REQUEST, {"code": "body_not_allowed"})
                return
            response, started = state.start()
            self.send_json(HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT, response)

    return Handler


def main() -> int:
    token = require_token(os.environ.get("KERAUN_LOCAL_CARTRIDGE_AGENT_TOKEN"))
    if not RUNNER.is_file() or not os.access(RUNNER, os.X_OK):
        raise SystemExit("local cartridge runner is unavailable")
    server = ThreadingHTTPServer((HOST, PORT), handler_for(AgentState(token)))
    print(f"Keraun local cartridge agent listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
