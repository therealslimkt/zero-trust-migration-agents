from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from cloud_runtime.google_adapters import (
    BigQueryWarehouseGateway,
    DataflowRestGateway,
    GCSObjectStore,
)
from cloud_runtime.orchestrator import CloudPortfolioResult, CloudSourceResult
from control_plane.canonical import SOURCE_ORDER, TARGET_TABLES, canonical_json_bytes
from control_plane.workflow import prepare_portfolio
from scripts import run_m4_cloud as cli
from tests.control_plane.test_workflow import FakeCompiler, SENTINEL, _artifacts


PROJECT = "ztm-agent-9049c3"
REGION = "us-central1"
DATASET = "legacy_migration"
APPROVED_AT = "2026-08-26T22:00:00.000Z"


def _prepared():
    return asyncio.run(
        prepare_portfolio(artifacts_by_source=_artifacts(), compiler=FakeCompiler())
    )


def _write_snapshot(path, prepared, *, mode=0o600):
    path.write_bytes(canonical_json_bytes(prepared.as_document()))
    path.chmod(mode)


def _args(prepared, snapshot, output, *extra):
    values = [
        "--snapshot",
        str(snapshot),
        "--digest",
        prepared.portfolio_digest,
        "--approver",
        "portfolio-reviewer",
        "--approved-at",
        APPROVED_AT,
        "--output",
        str(output),
        "--project",
        PROJECT,
        "--region",
        REGION,
        "--ingress-bucket",
        f"{PROJECT}-ingress",
        "--dataset",
        DATASET,
        "--flex-template-spec-uri",
        f"gs://{PROJECT}-templates/ztm.json",
        "--worker-service-account",
        f"worker@{PROJECT}.iam.gserviceaccount.com",
        "--worker-subnetwork",
        f"regions/{REGION}/subnetworks/ztm-dataflow",
        "--sdk-container-image",
        f"{REGION}-docker.pkg.dev/{PROJECT}/dataflow/ztm@sha256:" + "a" * 64,
        "--temp-location",
        f"gs://{PROJECT}-temp/dataflow",
    ]
    values.extend(extra)
    return cli._parser().parse_args(values)


def _cloud_result(prepared, execution):
    digests = {
        "bundle": "sha256:" + "b" * 64,
        "approval": "sha256:" + "c" * 64,
        "policy": "sha256:" + "d" * 64,
    }
    sources = tuple(
        CloudSourceResult(
            source_id=source_id,
            job_id=f"job_{source_id}_20260826",
            job_name=f"ztm-{source_id}-approved-proof",
            terminal_state="JOB_STATE_DONE",
            table_spec=f"{PROJECT}:{DATASET}.{TARGET_TABLES[source_id]}",
            record_count=reconciliation.record_count,
            plan_digest=prepared.plans[index]["planDigest"],
            output_digest=reconciliation.output_digest,
            bundle_digest=digests["bundle"],
            approval_digest=digests["approval"],
            policy_digest=digests["policy"],
        )
        for index, (source_id, reconciliation) in enumerate(
            zip(SOURCE_ORDER, execution.reconciliations)
        )
    )
    return CloudPortfolioResult(
        run_id=prepared.run_id,
        portfolio_digest=prepared.portfolio_digest,
        audit_digest="sha256:" + "e" * 64,
        sources=sources,
    )


def test_run_executes_local_portfolio_before_constructing_clients_and_writes_safe_proof(
    tmp_path,
):
    prepared = _prepared()
    snapshot = tmp_path / "prepared.json"
    output = tmp_path / "cloud-proof.json"
    _write_snapshot(snapshot, prepared)
    args = _args(prepared, snapshot, output)

    storage_client = object()
    bigquery_client = object()
    dataflow_client = object()
    events = []
    real_execute = cli.execute_portfolio

    def local_execute(**kwargs):
        events.append("local")
        assert kwargs["approval"].timestamp == APPROVED_AT
        assert kwargs["approval"].approver == "portfolio-reviewer"
        return real_execute(**kwargs)

    def clients(**kwargs):
        events.append("clients")
        assert kwargs == {"project": PROJECT, "region": REGION}
        return cli.GoogleClients(storage_client, bigquery_client, dataflow_client)

    def cloud_execute(**kwargs):
        events.append("cloud")
        assert isinstance(kwargs["object_store"], GCSObjectStore)
        assert isinstance(kwargs["dataflow"], DataflowRestGateway)
        assert isinstance(kwargs["warehouse"], BigQueryWarehouseGateway)
        assert kwargs["object_store"]._client is storage_client
        assert kwargs["dataflow"]._service is dataflow_client
        assert kwargs["warehouse"]._client is bigquery_client
        assert kwargs["config"].sdk_container_image.endswith("a" * 64)
        return _cloud_result(prepared, kwargs["execution"])

    with (
        mock.patch.object(cli, "execute_portfolio", side_effect=local_execute),
        mock.patch.object(
            cli, "execute_cloud_portfolio", side_effect=cloud_execute
        ),
    ):
        proof = cli.run(args, client_factory=clients)

    assert events == ["local", "clients", "cloud"]
    assert json.loads(output.read_bytes()) == proof
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert proof["sourceCount"] == 3
    assert [source["sourceId"] for source in proof["sources"]] == list(SOURCE_ORDER)
    encoded = output.read_text()
    assert SENTINEL not in encoded
    assert "portfolio-reviewer" not in encoded
    assert APPROVED_AT not in encoded
    assert set(proof) == {
        "runId",
        "portfolioDigest",
        "auditDigest",
        "sourceCount",
        "sources",
    }


@pytest.mark.parametrize(
    "argument,replacement,error",
    [
        ("digest", "sha256:" + "0" * 64, "approval_digest"),
        ("approved_at", "2026-08-26T17:00:00-05:00", "approval_timestamp"),
        ("approved_at", "2026-08-26T22:00:00.00Z", "approval_timestamp"),
        ("approver", " reviewer", "approval_identity"),
    ],
)
def test_invalid_approval_never_executes_or_constructs_clients(
    tmp_path, argument, replacement, error
):
    prepared = _prepared()
    snapshot = tmp_path / "prepared.json"
    output = tmp_path / "cloud-proof.json"
    _write_snapshot(snapshot, prepared)
    args = _args(prepared, snapshot, output)
    setattr(args, argument, replacement)

    with mock.patch.object(cli, "execute_portfolio") as local_execute:
        with pytest.raises(cli.M4CompositionError, match=f"^{error}$"):
            cli.run(
                args,
                client_factory=lambda **_kwargs: pytest.fail(
                    "client construction must not occur"
                ),
            )

    local_execute.assert_not_called()
    assert not output.exists()


def test_snapshot_must_be_owner_only_canonical_and_not_a_symlink(tmp_path):
    prepared = _prepared()
    output = tmp_path / "cloud-proof.json"

    permissive = tmp_path / "permissive.json"
    _write_snapshot(permissive, prepared, mode=0o640)
    with pytest.raises(cli.M4CompositionError, match="^snapshot_permissions$"):
        cli.run(_args(prepared, permissive, output), client_factory=mock.Mock())

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(
        json.dumps(prepared.as_document(), sort_keys=True, indent=2)
    )
    noncanonical.chmod(0o600)
    with pytest.raises(cli.M4CompositionError, match="^snapshot_not_canonical$"):
        cli.run(_args(prepared, noncanonical, output), client_factory=mock.Mock())

    link = tmp_path / "prepared-link.json"
    os.symlink(permissive, link)
    with pytest.raises(cli.M4CompositionError, match="^snapshot_unavailable$"):
        cli.run(_args(prepared, link, output), client_factory=mock.Mock())

    assert not output.exists()


def test_existing_output_prevents_client_construction_and_is_not_overwritten(tmp_path):
    prepared = _prepared()
    snapshot = tmp_path / "prepared.json"
    output = tmp_path / "cloud-proof.json"
    _write_snapshot(snapshot, prepared)
    output.write_text("existing proof")
    output.chmod(0o600)

    with pytest.raises(cli.M4CompositionError, match="^output_exists$"):
        cli.run(
            _args(prepared, snapshot, output),
            client_factory=lambda **_kwargs: pytest.fail(
                "client construction must not occur"
            ),
        )

    assert output.read_text() == "existing proof"


def test_invalid_temp_location_precedes_execution_and_client_construction(tmp_path):
    prepared = _prepared()
    snapshot = tmp_path / "prepared.json"
    output = tmp_path / "cloud-proof.json"
    _write_snapshot(snapshot, prepared)
    args = _args(prepared, snapshot, output)
    args.temp_location = "https://storage.googleapis.com/not-gcs"

    with mock.patch.object(cli, "execute_portfolio") as local_execute:
        with pytest.raises(cli.M4CompositionError, match="^cloud_temp_location$"):
            cli.run(
                args,
                client_factory=lambda **_kwargs: pytest.fail(
                    "client construction must not occur"
                ),
            )

    local_execute.assert_not_called()
    assert not output.exists()


def test_provider_failure_removes_only_the_reserved_empty_output(tmp_path):
    prepared = _prepared()
    snapshot = tmp_path / "prepared.json"
    output = tmp_path / "cloud-proof.json"
    _write_snapshot(snapshot, prepared)

    def fail_cloud(**_kwargs):
        raise RuntimeError("provider detail that must not be persisted")

    with mock.patch.object(cli, "execute_cloud_portfolio", side_effect=fail_cloud):
        with pytest.raises(RuntimeError, match="provider detail"):
            cli.run(
                _args(prepared, snapshot, output),
                client_factory=lambda **_kwargs: cli.GoogleClients(
                    object(), object(), object()
                ),
            )

    assert not output.exists()


def test_script_never_reads_browser_prefixed_or_cloud_credential_environment():
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "VITE_MISSION" not in source
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in source
    assert source.count("os.environ.get") == 2


class _MissionControlRecorder:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def get_run(self, run_id):
        return {
            "runId": run_id,
            "sources": [
                {"sourceId": source_id, "state": self.state}
                for source_id in SOURCE_ORDER
            ],
        }

    def advance_source(self, **kwargs):
        self.calls.append(kwargs)


def test_mission_control_sync_is_retry_aware_and_carries_all_cloud_evidence():
    prepared = _prepared()
    approval = cli._approval(
        prepared=prepared,
        digest=prepared.portfolio_digest,
        approver="portfolio-reviewer",
        approved_at=APPROVED_AT,
    )
    execution = cli.execute_portfolio(
        prepared=prepared,
        approval=approval,
        policy_categories=frozenset(),
    )
    result = _cloud_result(prepared, execution)
    recorder = _MissionControlRecorder("approved")

    cli._sync_cloud_evidence(recorder, result)

    assert len(recorder.calls) == 9
    for index in range(0, len(recorder.calls), 3):
        executing, verifying, completed = recorder.calls[index : index + 3]
        assert executing["state"] == "executing"
        assert verifying["state"] == "verifying"
        assert "dataflow" in verifying["artifact_id"]
        assert "bigquery" in verifying["secondary_artifact_id"]
        assert completed["state"] == "completed"
        assert "reconcile" in completed["artifact_id"]
        assert "audit" in completed["secondary_artifact_id"]

    already_complete = _MissionControlRecorder("completed")
    cli._sync_cloud_evidence(already_complete, result)
    assert already_complete.calls == []
