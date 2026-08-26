"""Port-level orchestration for immutable storage, Dataflow, and BigQuery.

Google SDK adapters implement these protocols.  Keeping SDK clients outside
this module makes approval and reconciliation behavior deterministic and
fully testable without credentials or network access.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Iterable, Mapping
from typing import Protocol

from control_plane.canonical import SOURCE_ORDER, TARGET_TABLES, require_digest
from control_plane.workflow import PreparedPortfolio, PortfolioExecutionResult
from ztm_security.approval import ApprovalRecord

from .bundle import CloudBundle, build_cloud_bundles
from .dataflow_template import bigquery_schema


class CloudExecutionRejected(RuntimeError):
    """A safe cloud-execution failure that never reflects provider output."""


_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_REGION_RE = re.compile(r"^[a-z]+-[a-z]+[0-9]$")
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
_SERVICE_ACCOUNT_RE = re.compile(
    r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$"
)
_JOB_ID_RE = re.compile(r"^[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$")


def _reject(code: str) -> None:
    raise CloudExecutionRejected(code)


@dataclasses.dataclass(frozen=True)
class CloudRuntimeConfig:
    project: str
    region: str
    ingress_bucket: str
    dataset: str
    flex_template_spec_uri: str
    worker_service_account: str

    def __post_init__(self) -> None:
        if _PROJECT_RE.fullmatch(self.project) is None:
            _reject("cloud_config")
        if _REGION_RE.fullmatch(self.region) is None:
            _reject("cloud_config")
        if _BUCKET_RE.fullmatch(self.ingress_bucket) is None:
            _reject("cloud_config")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,1023}", self.dataset):
            _reject("cloud_config")
        if not self.flex_template_spec_uri.startswith("gs://"):
            _reject("cloud_config")
        if _SERVICE_ACCOUNT_RE.fullmatch(self.worker_service_account) is None:
            _reject("cloud_config")


@dataclasses.dataclass(frozen=True)
class WarehouseObservation:
    row_count: int
    distinct_ordinal_count: int
    plan_digests: frozenset[str]
    output_digests: frozenset[str]
    bundle_digests: frozenset[str]


@dataclasses.dataclass(frozen=True)
class CloudSourceResult:
    source_id: str
    job_id: str
    terminal_state: str
    table_spec: str
    record_count: int
    plan_digest: str
    output_digest: str
    bundle_digest: str


@dataclasses.dataclass(frozen=True)
class CloudPortfolioResult:
    run_id: str
    portfolio_digest: str
    sources: tuple[CloudSourceResult, ...]


class ImmutableObjectStore(Protocol):
    def ensure_object(
        self, *, bucket: str, name: str, payload: bytes, digest: str
    ) -> str:
        """Create once or prove an existing object's bytes have this digest."""


class DataflowGateway(Protocol):
    def launch_flex_template(
        self,
        *,
        project: str,
        region: str,
        job_name: str,
        template_spec_uri: str,
        worker_service_account: str,
        parameters: Mapping[str, str],
        labels: Mapping[str, str],
    ) -> str: ...

    def wait_for_terminal(self, *, project: str, region: str, job_id: str) -> str: ...


class WarehouseGateway(Protocol):
    def observe_lineage(
        self,
        *,
        table_spec: str,
        run_id: str,
        source_id: str,
        output_digest: str,
    ) -> WarehouseObservation: ...


def _bundle_by_source(bundles: tuple[CloudBundle, ...]) -> dict[str, CloudBundle]:
    if tuple(bundle.source_id for bundle in bundles) != SOURCE_ORDER:
        _reject("cloud_bundle_order")
    return {bundle.source_id: bundle for bundle in bundles}


def _job_name(run_id: str, bundle: CloudBundle) -> str:
    suffix = run_id.removeprefix("mig_").lower()[:16]
    digest = bundle.digest.removeprefix("sha256:")[:12]
    return f"ztm-{bundle.source_id}-{suffix}-{digest}"[:63].rstrip("-")


def _launch_parameters(
    config: CloudRuntimeConfig, bundle: CloudBundle
) -> tuple[str, dict[str, str]]:
    document = bundle.as_document()
    source_id = bundle.source_id
    target = document.get("target")
    if target != {"dataset": config.dataset, "table": TARGET_TABLES[source_id]}:
        _reject("cloud_destination")
    table_spec = f"{config.project}:{config.dataset}.{TARGET_TABLES[source_id]}"
    parameters = {
        "input_uri": f"gs://{config.ingress_bucket}/{bundle.object_name}",
        "output_table": table_spec,
        "expected_run_id": str(document["runId"]),
        "expected_source_id": source_id,
        "expected_portfolio_digest": str(document["portfolioDigest"]),
        "expected_plan_digest": str(document["planDigest"]),
        "expected_bundle_digest": bundle.digest,
        "output_schema_json": json.dumps(
            bigquery_schema(document["outputFields"]),
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    return table_spec, parameters


def execute_cloud_portfolio(
    *,
    prepared: PreparedPortfolio,
    execution: PortfolioExecutionResult,
    approval: ApprovalRecord,
    policy_categories: Iterable[str],
    config: CloudRuntimeConfig,
    object_store: ImmutableObjectStore,
    dataflow: DataflowGateway,
    warehouse: WarehouseGateway,
) -> CloudPortfolioResult:
    """Run all three sources and return only after exact warehouse proof.

    All validation and bundle construction occurs before the first side effect.
    If any provider call fails, no success result is returned. Already-started
    provider jobs may still require operational cleanup; their outputs remain
    lineage-scoped and can never be mistaken for a completed portfolio.
    """

    try:
        bundles = build_cloud_bundles(
            prepared=prepared,
            execution=execution,
            approval=approval,
            policy_categories=policy_categories,
        )
        by_source = _bundle_by_source(bundles)
        launch_specs: list[tuple[str, CloudBundle, str, dict[str, str]]] = []
        for source_id in SOURCE_ORDER:
            bundle = by_source[source_id]
            table_spec, parameters = _launch_parameters(config, bundle)
            launch_specs.append((source_id, bundle, table_spec, parameters))
    except CloudExecutionRejected:
        raise
    except Exception:
        _reject("cloud_preflight")

    # Upload every content-addressed input before starting compute.
    try:
        for _, bundle, _, _ in launch_specs:
            observed = object_store.ensure_object(
                bucket=config.ingress_bucket,
                name=bundle.object_name,
                payload=bundle.payload,
                digest=bundle.digest,
            )
            if observed != bundle.digest:
                _reject("cloud_storage_binding")
    except CloudExecutionRejected:
        raise
    except Exception:
        _reject("cloud_storage")

    launched: list[tuple[str, CloudBundle, str, str]] = []
    try:
        for source_id, bundle, table_spec, parameters in launch_specs:
            job_id = dataflow.launch_flex_template(
                project=config.project,
                region=config.region,
                job_name=_job_name(prepared.run_id, bundle),
                template_spec_uri=config.flex_template_spec_uri,
                worker_service_account=config.worker_service_account,
                parameters=parameters,
                labels={"ztm_source": source_id, "ztm_run": prepared.run_id.lower()},
            )
            if not isinstance(job_id, str) or _JOB_ID_RE.fullmatch(job_id) is None:
                _reject("cloud_job_id")
            launched.append((source_id, bundle, table_spec, job_id))
    except CloudExecutionRejected:
        raise
    except Exception:
        _reject("cloud_launch")

    results: list[CloudSourceResult] = []
    try:
        for source_id, bundle, table_spec, job_id in launched:
            terminal = dataflow.wait_for_terminal(
                project=config.project, region=config.region, job_id=job_id
            )
            if terminal != "JOB_STATE_DONE":
                _reject("cloud_job_failed")
            document = bundle.as_document()
            observation = warehouse.observe_lineage(
                table_spec=table_spec,
                run_id=prepared.run_id,
                source_id=source_id,
                output_digest=str(document["outputDigest"]),
            )
            expected_count = int(document["recordCount"])
            if (
                type(observation.row_count) is not int
                or observation.row_count != expected_count
                or observation.distinct_ordinal_count != expected_count
                or observation.plan_digests != frozenset({document["planDigest"]})
                or observation.output_digests
                != frozenset({document["outputDigest"]})
                or observation.bundle_digests != frozenset({bundle.digest})
            ):
                _reject("cloud_reconciliation")
            for digest in (
                str(document["planDigest"]),
                str(document["outputDigest"]),
                bundle.digest,
            ):
                require_digest(digest)
            results.append(
                CloudSourceResult(
                    source_id=source_id,
                    job_id=job_id,
                    terminal_state=terminal,
                    table_spec=table_spec,
                    record_count=expected_count,
                    plan_digest=str(document["planDigest"]),
                    output_digest=str(document["outputDigest"]),
                    bundle_digest=bundle.digest,
                )
            )
    except CloudExecutionRejected:
        raise
    except Exception:
        _reject("cloud_verification")

    if tuple(result.source_id for result in results) != SOURCE_ORDER:
        _reject("cloud_incomplete")
    return CloudPortfolioResult(
        run_id=prepared.run_id,
        portfolio_digest=prepared.portfolio_digest,
        sources=tuple(results),
    )
