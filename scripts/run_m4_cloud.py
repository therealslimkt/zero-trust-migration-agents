#!/usr/bin/env python3
"""Execute one approved M4 portfolio through the trusted Google Cloud ports.

This entry point deliberately performs no planning and accepts no record data
on the command line.  It reopens the canonical, owner-only M3 snapshot, binds
an explicit human approval to its exact digest, runs the closed local
interpreter, and only then constructs the Google SDK clients and adapters.

Successful output is a new 0600 file containing identifiers, counts, and
digests only.  Protected rows, approval identities, SDK responses, credentials,
and environment variables are never included in that proof.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hmac
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cloud_runtime.google_adapters import (
    BigQueryWarehouseGateway,
    DataflowRestGateway,
    GCSObjectStore,
)
from cloud_runtime.orchestrator import (
    CloudPortfolioResult,
    CloudRuntimeConfig,
    CloudSourceResult,
    execute_cloud_portfolio,
)
from control_plane.canonical import (
    SOURCE_ORDER,
    TARGET_TABLES,
    canonical_json_bytes,
    require_digest,
    require_run_id,
)
from control_plane.mission_control_client import MissionControlLocalClient
from control_plane.workflow import PreparedPortfolio, execute_portfolio
from ztm_security.approval import ApprovalRecord


_MAX_SNAPSHOT_BYTES = 16 << 20
_RFC3339_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{3})?Z$"
)
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_JOB_NAME = re.compile(r"^ztm-(?:jde|maxdb|btrieve)-[a-z0-9-]{1,55}$")
_GCS_TEMP_LOCATION = re.compile(
    r"^gs://[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]/[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}$"
)
_EMPTY_POLICY_CATEGORIES = frozenset()


class M4CompositionError(RuntimeError):
    """A fixed-vocabulary local rejection that contains no input data."""


def _reject(code: str) -> None:
    raise M4CompositionError(code)


@dataclasses.dataclass(frozen=True)
class GoogleClients:
    """Already-created official clients, injectable for credential-free tests."""

    storage: Any
    bigquery: Any
    dataflow: Any


ClientFactory = Callable[..., GoogleClients]


def official_client_factory(*, project: str, region: str) -> GoogleClients:
    """Construct the three official clients at the last responsible moment.

    Imports are intentionally lazy: malformed or unapproved local input cannot
    trigger application-default credential discovery.
    """

    from google.cloud import bigquery, storage
    from googleapiclient.discovery import build

    return GoogleClients(
        storage=storage.Client(project=project),
        bigquery=bigquery.Client(project=project, location=region),
        dataflow=build("dataflow", "v1b3", cache_discovery=False),
    )


def _stable_stat(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mode,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


def _load_prepared(path: Path) -> PreparedPortfolio:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        _reject("snapshot_unavailable")

    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o077
            or before.st_size <= 0
            or before.st_size > _MAX_SNAPSHOT_BYTES
        ):
            _reject("snapshot_permissions")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(_MAX_SNAPSHOT_BYTES + 1)
        after = os.fstat(descriptor)
    except M4CompositionError:
        raise
    except OSError:
        _reject("snapshot_unavailable")
    finally:
        os.close(descriptor)

    if (
        len(payload) > _MAX_SNAPSHOT_BYTES
        or len(payload) != before.st_size
        or _stable_stat(before) != _stable_stat(after)
    ):
        _reject("snapshot_changed")
    try:
        document = json.loads(payload.decode("utf-8"))
        if type(document) is not dict:
            raise ValueError
        canonical = canonical_json_bytes(document)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        _reject("snapshot_invalid")
    if not hmac.compare_digest(payload, canonical):
        _reject("snapshot_not_canonical")
    return PreparedPortfolio(canonical)


def _approval(
    *,
    prepared: PreparedPortfolio,
    digest: str,
    approver: str | None,
    approved_at: str | None,
) -> ApprovalRecord:
    try:
        require_digest(digest)
    except (TypeError, ValueError):
        _reject("approval_digest")
    if not hmac.compare_digest(digest, prepared.portfolio_digest):
        _reject("approval_digest")
    if (
        not isinstance(approver, str)
        or not approver
        or approver != approver.strip()
        or len(approver) > 128
        or not all(character.isprintable() for character in approver)
    ):
        _reject("approval_identity")
    if not isinstance(approved_at, str) or _RFC3339_UTC.fullmatch(approved_at) is None:
        _reject("approval_timestamp")
    try:
        parsed = dt.datetime.fromisoformat(approved_at[:-1] + "+00:00")
    except ValueError:
        _reject("approval_timestamp")
    if parsed.utcoffset() != dt.timedelta(0):
        _reject("approval_timestamp")
    try:
        return ApprovalRecord(
            approver=approver,
            plan_digest=digest,
            timestamp=approved_at,
            portfolio_run_id=prepared.run_id,
        )
    except (TypeError, ValueError):
        _reject("approval_invalid")


def _runtime_config(args: argparse.Namespace) -> CloudRuntimeConfig:
    config = CloudRuntimeConfig(
        project=args.project,
        region=args.region,
        ingress_bucket=args.ingress_bucket,
        dataset=args.dataset,
        flex_template_spec_uri=args.flex_template_spec_uri,
        worker_service_account=args.worker_service_account,
        worker_subnetwork=args.worker_subnetwork,
        sdk_container_image=args.sdk_container_image,
    )
    if (
        not isinstance(args.temp_location, str)
        or _GCS_TEMP_LOCATION.fullmatch(args.temp_location) is None
        or "/../" in args.temp_location
        or args.temp_location.endswith("/..")
        or "//" in args.temp_location.removeprefix("gs://")
    ):
        _reject("cloud_temp_location")
    return config


def _reserve_output(path: Path) -> int:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        _reject("output_exists")
    except OSError:
        _reject("output_unavailable")
    try:
        os.fchmod(descriptor, 0o600)
        return descriptor
    except OSError:
        _discard_output(path, descriptor)
        os.close(descriptor)
        _reject("output_unavailable")


def _discard_output(path: Path, descriptor: int) -> None:
    """Remove only the exact inode reserved by this process."""

    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            stat.S_ISREG(named.st_mode)
            and (opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino)
        ):
            os.unlink(path)
    except OSError:
        pass


def _commit_output(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            _reject("output_write")
        view = view[written:]
    os.fsync(descriptor)


def _validated_digest(value: object) -> str:
    try:
        require_digest(value)
    except (TypeError, ValueError):
        _reject("cloud_proof")
    return str(value)


def _proof(
    result: CloudPortfolioResult,
    config: CloudRuntimeConfig,
    *,
    expected_run_id: str,
    expected_portfolio_digest: str,
) -> dict[str, object]:
    if (
        not isinstance(result, CloudPortfolioResult)
        or result.run_id != expected_run_id
        or result.portfolio_digest != expected_portfolio_digest
    ):
        _reject("cloud_proof")
    try:
        require_run_id(result.run_id)
    except (TypeError, ValueError):
        _reject("cloud_proof")
    if tuple(source.source_id for source in result.sources) != SOURCE_ORDER:
        _reject("cloud_proof")

    sources: list[dict[str, object]] = []
    for source_id, source in zip(SOURCE_ORDER, result.sources):
        if not isinstance(source, CloudSourceResult):
            _reject("cloud_proof")
        expected_table = f"{config.project}:{config.dataset}.{TARGET_TABLES[source_id]}"
        if (
            source.table_spec != expected_table
            or _JOB_ID.fullmatch(source.job_id) is None
            or _JOB_NAME.fullmatch(source.job_name) is None
            or source.terminal_state != "JOB_STATE_DONE"
            or type(source.record_count) is not int
            or source.record_count < 0
        ):
            _reject("cloud_proof")
        sources.append(
            {
                "sourceId": source_id,
                "jobId": source.job_id,
                "jobName": source.job_name,
                "tableSpec": source.table_spec,
                "recordCount": source.record_count,
                "planDigest": _validated_digest(source.plan_digest),
                "outputDigest": _validated_digest(source.output_digest),
                "bundleDigest": _validated_digest(source.bundle_digest),
                "approvalDigest": _validated_digest(source.approval_digest),
                "policyDigest": _validated_digest(source.policy_digest),
            }
        )
    return {
        "runId": result.run_id,
        "portfolioDigest": _validated_digest(result.portfolio_digest),
        "auditDigest": _validated_digest(result.audit_digest),
        "sourceCount": len(sources),
        "sources": sources,
    }


def run(
    args: argparse.Namespace,
    *,
    client_factory: ClientFactory = official_client_factory,
) -> dict[str, object]:
    """Compose the approved local and cloud executions and persist safe proof."""

    prepared = _load_prepared(args.snapshot)
    mission_control: MissionControlLocalClient | None = None
    if args.mission_control_url:
        mission_control = MissionControlLocalClient(
            base_url=args.mission_control_url,
            public_token=os.environ.get("MISSION_CONTROL_API_TOKEN"),
            orchestration_token=os.environ.get(
                "MISSION_CONTROL_ORCHESTRATOR_TOKEN"
            ),
        )
        approval = mission_control.approval(prepared.run_id)
        if not hmac.compare_digest(approval.plan_digest, args.digest):
            _reject("approval_digest")
    else:
        approval = _approval(
            prepared=prepared,
            digest=args.digest,
            approver=args.approver,
            approved_at=args.approved_at,
        )
    config = _runtime_config(args)
    execution = execute_portfolio(
        prepared=prepared,
        approval=approval,
        policy_categories=_EMPTY_POLICY_CATEGORIES,
    )

    descriptor = _reserve_output(args.output)
    committed = False
    try:
        clients = client_factory(project=config.project, region=config.region)
        if not isinstance(clients, GoogleClients):
            _reject("cloud_clients")
        cloud_result = execute_cloud_portfolio(
            prepared=prepared,
            execution=execution,
            approval=approval,
            policy_categories=_EMPTY_POLICY_CATEGORIES,
            config=config,
            object_store=GCSObjectStore(clients.storage),
            dataflow=DataflowRestGateway(
                clients.dataflow,
                temp_location=args.temp_location,
            ),
            warehouse=BigQueryWarehouseGateway(
                clients.bigquery,
                location=config.region,
            ),
        )
        proof = _proof(
            cloud_result,
            config,
            expected_run_id=prepared.run_id,
            expected_portfolio_digest=prepared.portfolio_digest,
        )
        if mission_control is not None:
            _sync_cloud_evidence(mission_control, cloud_result)
        _commit_output(descriptor, canonical_json_bytes(proof))
        committed = True
        return proof
    finally:
        if not committed:
            _discard_output(args.output, descriptor)
        os.close(descriptor)


_STATE_RANK = {
    "approved": 5,
    "executing": 6,
    "verifying": 7,
    "completed": 8,
}


def _sync_cloud_evidence(
    client: MissionControlLocalClient, result: CloudPortfolioResult
) -> None:
    run = client.get_run(result.run_id)
    source_states = {
        str(source["sourceId"]): str(source["state"])
        for source in run["sources"]  # type: ignore[index,union-attr]
        if type(source) is dict
    }
    for source in result.sources:
        state = source_states.get(source.source_id)
        if state not in _STATE_RANK:
            _reject("mission_control_state")
        if _STATE_RANK[state] < _STATE_RANK["executing"]:
            client.advance_source(
                run_id=result.run_id,
                source_id=source.source_id,
                state="executing",
            )
            state = "executing"
        if _STATE_RANK[state] < _STATE_RANK["verifying"]:
            client.advance_source(
                run_id=result.run_id,
                source_id=source.source_id,
                state="verifying",
                artifact_id=(
                    f"art_{source.source_id}-dataflow-{source.bundle_digest[7:19]}"
                ),
                digest=source.bundle_digest,
                secondary_artifact_id=(
                    f"art_{source.source_id}-bigquery-{source.output_digest[7:19]}"
                ),
                secondary_digest=source.output_digest,
                records_written=source.record_count,
                records_rejected=0,
            )
            state = "verifying"
        if _STATE_RANK[state] < _STATE_RANK["completed"]:
            client.advance_source(
                run_id=result.run_id,
                source_id=source.source_id,
                state="completed",
                artifact_id=(
                    f"art_{source.source_id}-reconcile-{source.output_digest[7:19]}"
                ),
                digest=source.output_digest,
                secondary_artifact_id=(
                    f"art_{source.source_id}-audit-{result.audit_digest[7:19]}"
                ),
                secondary_digest=result.audit_digest,
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an approved three-source portfolio on the trusted cloud runtime"
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--approver")
    parser.add_argument(
        "--approved-at",
        required=False,
        help="explicit UTC RFC3339 timestamp with seconds or milliseconds",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--ingress-bucket", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--flex-template-spec-uri", required=True)
    parser.add_argument("--worker-service-account", required=True)
    parser.add_argument("--worker-subnetwork", required=True)
    parser.add_argument("--sdk-container-image", required=True)
    parser.add_argument("--temp-location", required=True)
    parser.add_argument("--mission-control-url")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        run(args)
    except Exception:
        raise SystemExit("M4 cloud run failed") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
