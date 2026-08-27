from __future__ import annotations

import email.message
import json

import pytest

from control_plane.mission_control_client import (
    MissionControlLocalClient,
    MissionControlSyncError,
)


RUN_ID = "mig_MISSIONCLIENT01"
DIGEST = "sha256:" + "a" * 64


class _Response:
    def __init__(self, document, status=200):
        self.payload = json.dumps(document).encode()
        self.status = status
        self.headers = email.message.Message()
        self.headers["Content-Type"] = "application/json"

    def getcode(self):
        return self.status

    def read(self, size):
        return self.payload[:size]

    def close(self):
        pass


class _Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        assert timeout == 10.0
        self.requests.append(request)
        return self.responses.pop(0)


def _run(state="approved"):
    return {
        "schemaVersion": "1.0.0",
        "runId": RUN_ID,
        "state": state,
        "sources": [
            {"sourceId": source_id, "state": state}
            for source_id in ("jde", "maxdb", "btrieve")
        ],
    }


def test_client_uses_separate_tokens_and_closed_loopback_paths():
    opener = _Opener(
        [
            _Response(_run("created"), 202),
            _Response(_run("approved")),
            _Response(_run("executing")),
            _Response(
                {
                    "schemaVersion": "1.0.0",
                    "approvalId": "apr_MISSIONCLIENT01",
                    "runId": RUN_ID,
                    "planDigest": DIGEST,
                    "decision": "approve",
                    "resultingState": "approved",
                    "decidedBy": "portfolio-reviewer",
                    "decidedAt": "2026-08-26T22:00:00.000Z",
                }
            ),
        ]
    )
    client = MissionControlLocalClient(
        "http://127.0.0.1:8080",
        public_token="public-token",
        orchestration_token="orchestrator-token",
        opener=opener,
    )

    assert client.create_portfolio(
        portfolio_name="Legacy ERP Portfolio", requested_by="operator"
    ) == RUN_ID
    assert client.get_run(RUN_ID)["state"] == "approved"
    client.advance_source(run_id=RUN_ID, source_id="jde", state="executing")
    approval = client.approval(RUN_ID)

    assert approval.plan_digest == DIGEST
    assert approval.timestamp == "2026-08-26T22:00:00.000Z"
    assert [request.full_url for request in opener.requests] == [
        "http://127.0.0.1:8080/api/v1/migrations",
        f"http://127.0.0.1:8080/api/v1/migrations/{RUN_ID}",
        "http://127.0.0.1:8080/internal/v1/orchestration",
        f"http://127.0.0.1:8080/internal/v1/approvals/{RUN_ID}",
    ]
    assert opener.requests[0].get_header("Authorization") == "Bearer public-token"
    assert (
        opener.requests[2].get_header("Authorization")
        == "Bearer orchestrator-token"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8080",
        "http://example.com:8080",
        "http://user:pass@127.0.0.1:8080",
        "http://127.0.0.1:8080/path",
        "http://127.0.0.1",
    ],
)
def test_client_refuses_non_loopback_or_ambiguous_origins(url):
    with pytest.raises(MissionControlSyncError, match="^mission_control_config$"):
        MissionControlLocalClient(
            url,
            public_token="public-token",
            orchestration_token="orchestrator-token",
        )


def test_client_refuses_shared_or_header_unsafe_tokens():
    with pytest.raises(MissionControlSyncError, match="^mission_control_config$"):
        MissionControlLocalClient(
            "http://127.0.0.1:8080",
            public_token="same-token",
            orchestration_token="same-token",
        )
    with pytest.raises(MissionControlSyncError, match="^mission_control_config$"):
        MissionControlLocalClient(
            "http://127.0.0.1:8080",
            public_token="bad token",
        )
