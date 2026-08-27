"""Closed loopback client for the durable Mission Control event store."""

from __future__ import annotations

import dataclasses
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from control_plane.canonical import SOURCE_ORDER, require_digest, require_run_id
from ztm_security.approval import ApprovalRecord


class MissionControlSyncError(RuntimeError):
    """A fixed local error that never reflects response, token, or request data."""


_TOKEN_MAX = 512
_MAX_RESPONSE = 64 << 10
_ARTIFACT_ID = re.compile(r"^art_[A-Za-z0-9._-]{8,128}$")
_STATES = frozenset(
    {"inventorying", "redacting", "planning", "executing", "verifying", "completed"}
)
_HOSTS = {
    "jde": "legacy-jde-db",
    "maxdb": "legacy-maxdb",
    "btrieve": "legacy-btrieve-db",
}


def _reject(code: str) -> None:
    raise MissionControlSyncError(code)


def _token(value: str | None) -> str:
    if not isinstance(value, str) or not value or len(value) > _TOKEN_MAX:
        _reject("mission_control_config")
    if any(ord(character) <= 0x20 or ord(character) >= 0x7F for character in value):
        _reject("mission_control_config")
    return value


def _base_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        _reject("mission_control_config")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _reject("mission_control_config")
    try:
        port = parsed.port
    except ValueError:
        _reject("mission_control_config")
    if port is None or not 1 <= port <= 65535:
        _reject("mission_control_config")
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}:{port}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _open(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


OpenCall = Callable[[urllib.request.Request, float], object]


@dataclasses.dataclass(frozen=True)
class MissionControlLocalClient:
    base_url: str
    public_token: str | None = dataclasses.field(default=None, repr=False)
    orchestration_token: str | None = dataclasses.field(default=None, repr=False)
    opener: OpenCall = dataclasses.field(default=_open, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _base_url(self.base_url))
        if self.public_token is not None:
            object.__setattr__(self, "public_token", _token(self.public_token))
        if self.orchestration_token is not None:
            object.__setattr__(
                self, "orchestration_token", _token(self.orchestration_token)
            )
        if self.public_token is not None and self.public_token == self.orchestration_token:
            _reject("mission_control_config")

    def _request(
        self,
        *,
        path: str,
        token: str | None,
        method: str,
        body: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        bearer = _token(token)
        payload = None if body is None else json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {bearer}",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            response = self.opener(request, 10.0)
            status = response.getcode()
            content_type = response.headers.get_content_type()
            encoded = response.read(_MAX_RESPONSE + 1)
            response.close()
        except Exception:
            _reject("mission_control_unavailable")
        if status not in {200, 202} or content_type != "application/json":
            _reject("mission_control_response")
        if len(encoded) > _MAX_RESPONSE:
            _reject("mission_control_response")
        try:
            decoded = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _reject("mission_control_response")
        if type(decoded) is not dict:
            _reject("mission_control_response")
        return decoded

    def create_portfolio(self, *, portfolio_name: str, requested_by: str) -> str:
        response = self._request(
            path="/api/v1/migrations",
            token=self.public_token,
            method="POST",
            body={
                "schemaVersion": "1.0.0",
                "portfolioName": portfolio_name,
                "requestedBy": requested_by,
                "sources": [
                    {"sourceId": source_id, "hostname": _HOSTS[source_id]}
                    for source_id in SOURCE_ORDER
                ],
            },
        )
        run_id = response.get("runId")
        try:
            require_run_id(run_id)
        except (TypeError, ValueError):
            _reject("mission_control_response")
        return str(run_id)

    def get_run(self, run_id: str) -> dict[str, object]:
        try:
            require_run_id(run_id)
        except (TypeError, ValueError):
            _reject("mission_control_request")
        response = self._request(
            path=f"/api/v1/migrations/{run_id}",
            token=self.public_token,
            method="GET",
        )
        sources = response.get("sources")
        if (
            response.get("runId") != run_id
            or not isinstance(sources, list)
            or len(sources) != len(SOURCE_ORDER)
            or {source.get("sourceId") for source in sources if type(source) is dict}
            != set(SOURCE_ORDER)
        ):
            _reject("mission_control_response")
        return response

    def advance_source(
        self,
        *,
        run_id: str,
        source_id: str,
        state: str,
        artifact_id: str | None = None,
        digest: str | None = None,
        secondary_artifact_id: str | None = None,
        secondary_digest: str | None = None,
        records_read: int | None = None,
        records_written: int | None = None,
        records_rejected: int | None = None,
    ) -> None:
        if source_id not in SOURCE_ORDER or state not in _STATES:
            _reject("mission_control_request")
        body: dict[str, object] = {
            "schemaVersion": "1.0.0",
            "action": "advance_source",
            "runId": run_id,
            "sourceId": source_id,
            "state": state,
        }
        if artifact_id is not None or digest is not None:
            if (
                not isinstance(artifact_id, str)
                or _ARTIFACT_ID.fullmatch(artifact_id) is None
            ):
                _reject("mission_control_request")
            try:
                require_digest(digest)
            except (TypeError, ValueError):
                _reject("mission_control_request")
            body.update({"artifactId": artifact_id, "digest": digest})
        if secondary_artifact_id is not None or secondary_digest is not None:
            if (
                not isinstance(secondary_artifact_id, str)
                or _ARTIFACT_ID.fullmatch(secondary_artifact_id) is None
            ):
                _reject("mission_control_request")
            try:
                require_digest(secondary_digest)
            except (TypeError, ValueError):
                _reject("mission_control_request")
            body.update(
                {
                    "secondaryArtifactId": secondary_artifact_id,
                    "secondaryDigest": secondary_digest,
                }
            )
        for name, value in (
            ("recordsRead", records_read),
            ("recordsWritten", records_written),
            ("recordsRejected", records_rejected),
        ):
            if value is not None:
                if type(value) is not int or value < 0:
                    _reject("mission_control_request")
                body[name] = value
        self._request(
            path="/internal/v1/orchestration",
            token=self.orchestration_token,
            method="POST",
            body=body,
        )

    def attach_plan(
        self, *, run_id: str, source_id: str, artifact_id: str, digest: str
    ) -> None:
        if source_id not in SOURCE_ORDER or _ARTIFACT_ID.fullmatch(artifact_id) is None:
            _reject("mission_control_request")
        try:
            require_digest(digest)
        except (TypeError, ValueError):
            _reject("mission_control_request")
        self._request(
            path="/internal/v1/orchestration",
            token=self.orchestration_token,
            method="POST",
            body={
                "schemaVersion": "1.0.0",
                "action": "attach_source_plan",
                "runId": run_id,
                "sourceId": source_id,
                "artifactId": artifact_id,
                "digest": digest,
            },
        )

    def enter_awaiting_approval(self, run_id: str) -> None:
        self._request(
            path="/internal/v1/orchestration",
            token=self.orchestration_token,
            method="POST",
            body={
                "schemaVersion": "1.0.0",
                "action": "enter_awaiting_approval",
                "runId": run_id,
            },
        )

    def approval(self, run_id: str) -> ApprovalRecord:
        response = self._request(
            path=f"/internal/v1/approvals/{run_id}",
            token=self.orchestration_token,
            method="GET",
        )
        if (
            response.get("schemaVersion") != "1.0.0"
            or response.get("runId") != run_id
            or response.get("decision") != "approve"
            or response.get("resultingState") != "approved"
        ):
            _reject("mission_control_approval")
        try:
            return ApprovalRecord(
                approver=str(response["decidedBy"]),
                plan_digest=str(response["planDigest"]),
                timestamp=str(response["decidedAt"]),
                portfolio_run_id=run_id,
            )
        except (KeyError, TypeError, ValueError):
            _reject("mission_control_approval")
