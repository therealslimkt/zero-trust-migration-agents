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

from control_plane.canonical import (
    SOURCE_ORDER,
    TARGET_TABLES,
    document_digest,
    require_digest,
)
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
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


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
    worker_subnetwork: str
    sdk_container_image: str

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
        if re.fullmatch(
            rf"regions/{re.escape(self.region)}/subnetworks/[a-z][a-z0-9-]{{0,62}}",
            self.worker_subnetwork,
        ) is None:
            _reject("cloud_config")
        image_prefix = f"{self.region}-docker.pkg.dev/{self.project}/"
        if (
            not self.sdk_container_image.startswith(image_prefix)
            or re.fullmatch(
                r"[a-z0-9][a-z0-9._/-]{1,200}@sha256:[a-f0-9]{64}",
                self.sdk_container_image.removeprefix(image_prefix),
            )
            is None
        ):
            _reject("cloud_config")


@dataclasses.dataclass(frozen=True)
class WarehouseObservation:
    row_count: int
    distinct_ordinal_count: int
    minimum_ordinal: int | None
    maximum_ordinal: int | None
    plan_digests: frozenset[str]
    output_digests: frozenset[str]
    bundle_digests: frozenset[str]
    approval_digests: frozenset[str]
    policy_digests: frozenset[str]
    job_names: frozenset[str]


@dataclasses.dataclass(frozen=True)
class CloudSourceResult:
    source_id: str
    job_id: str
    job_name: str
    terminal_state: str
    table_spec: str
    record_count: int
    plan_digest: str
    output_digest: str
    bundle_digest: str
    approval_digest: str
    policy_digest: str


@dataclasses.dataclass(frozen=True)
class CloudPortfolioResult:
    run_id: str
    portfolio_digest: str
    audit_digest: str
    sources: tuple[CloudSourceResult, ...]


class ImmutableObjectStore(Protocol):
    def ensure_object(
        self, *, bucket: str, name: str, payload: bytes, digest: str
    ) -> str:
        """Create once or prove an existing object's bytes have this digest."""


class DataflowGateway(Protocol):
    def find_job_by_name(
        self, *, project: str, region: str, job_name: str
    ) -> str | None: ...

    def launch_flex_template(
        self,
        *,
        project: str,
        region: str,
        job_name: str,
        template_spec_uri: str,
        worker_service_account: str,
        worker_subnetwork: str,
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

    def ensure_portfolio_audit(
        self,
        *,
        run_id: str,
        portfolio_digest: str,
        audit_digest: str,
        sources: tuple[CloudSourceResult, ...],
    ) -> str: ...


def _bundle_by_source(bundles: tuple[CloudBundle, ...]) -> dict[str, CloudBundle]:
    if tuple(bundle.source_id for bundle in bundles) != SOURCE_ORDER:
        _reject("cloud_bundle_order")
    return {bundle.source_id: bundle for bundle in bundles}


def _job_name(run_id: str, bundle: CloudBundle) -> str:
    suffix = run_id.removeprefix("mig_").lower()[:16]
    digest = bundle.digest.removeprefix("sha256:")[:12]
    return f"ztm-{bundle.source_id}-{suffix}-{digest}"[:63].rstrip("-")


def _launch_parameters(
    config: CloudRuntimeConfig, bundle: CloudBundle, job_name: str
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
        "expected_job_name": job_name,
        "sdk_container_image": config.sdk_container_image,
    }
    return table_spec, parameters


def _empty_observation(observation: WarehouseObservation) -> bool:
    return observation == WarehouseObservation(
        row_count=0,
        distinct_ordinal_count=0,
        minimum_ordinal=None,
        maximum_ordinal=None,
        plan_digests=frozenset(),
        output_digests=frozenset(),
        bundle_digests=frozenset(),
        approval_digests=frozenset(),
        policy_digests=frozenset(),
        job_names=frozenset(),
    )


def _reconciles(
    observation: WarehouseObservation,
    *,
    document: Mapping[str, object],
    bundle: CloudBundle,
    job_name: str,
) -> bool:
    expected_count = int(document["recordCount"])
    return (
        type(observation.row_count) is int
        and observation.row_count == expected_count
        and type(observation.distinct_ordinal_count) is int
        and observation.distinct_ordinal_count == expected_count
        and observation.minimum_ordinal == (0 if expected_count else None)
        and observation.maximum_ordinal
        == (expected_count - 1 if expected_count else None)
        and observation.plan_digests == frozenset({document["planDigest"]})
        and observation.output_digests == frozenset({document["outputDigest"]})
        and observation.bundle_digests == frozenset({bundle.digest})
        and observation.approval_digests
        == frozenset({document["approvalDigest"]})
        and observation.policy_digests == frozenset({document["policyDigest"]})
        and observation.job_names == frozenset({job_name})
    )


def _audit_digest(
    run_id: str,
    portfolio_digest: str,
    sources: tuple[CloudSourceResult, ...],
) -> str:
    return document_digest(
        {
            "schemaVersion": "1.0.0",
            "kind": "cloud-portfolio-audit",
            "runId": run_id,
            "portfolioDigest": portfolio_digest,
            "sources": [dataclasses.asdict(source) for source in sources],
        }
    )


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
        launch_specs: list[
            tuple[str, CloudBundle, str, str, dict[str, str]]
        ] = []
        for source_id in SOURCE_ORDER:
            bundle = by_source[source_id]
            job_name = _job_name(prepared.run_id, bundle)
            table_spec, parameters = _launch_parameters(config, bundle, job_name)
            launch_specs.append(
                (source_id, bundle, job_name, table_spec, parameters)
            )
    except CloudExecutionRejected:
        raise
    except Exception:
        _reject("cloud_preflight")

    # Upload every content-addressed input before starting compute.
    try:
        for _, bundle, _, _, _ in launch_specs:
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

    resolved: list[tuple[str, CloudBundle, str, str, str]] = []
    try:
        for source_id, bundle, job_name, table_spec, parameters in launch_specs:
            document = bundle.as_document()
            before = warehouse.observe_lineage(
                table_spec=table_spec,
                run_id=prepared.run_id,
                source_id=source_id,
                output_digest=str(document["outputDigest"]),
            )
            existing_job_id = dataflow.find_job_by_name(
                project=config.project, region=config.region, job_name=job_name
            )
            if not _empty_observation(before) and not _reconciles(
                before, document=document, bundle=bundle, job_name=job_name
            ):
                _reject("cloud_existing_lineage")
            if existing_job_id is None:
                if not _empty_observation(before):
                    _reject("cloud_orphan_lineage")
                job_id = dataflow.launch_flex_template(
                    project=config.project,
                    region=config.region,
                    job_name=job_name,
                    template_spec_uri=config.flex_template_spec_uri,
                    worker_service_account=config.worker_service_account,
                    worker_subnetwork=config.worker_subnetwork,
                    parameters=parameters,
                    labels={
                        "ztm_source": source_id,
                        "ztm_run": prepared.run_id.lower(),
                    },
                )
            else:
                job_id = existing_job_id
            if not isinstance(job_id, str) or _JOB_ID_RE.fullmatch(job_id) is None:
                _reject("cloud_job_id")
            resolved.append((source_id, bundle, job_name, table_spec, job_id))
    except CloudExecutionRejected:
        raise
    except Exception:
        _reject("cloud_launch")

    results: list[CloudSourceResult] = []
    try:
        for source_id, bundle, job_name, table_spec, job_id in resolved:
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
            if not _reconciles(
                observation,
                document=document,
                bundle=bundle,
                job_name=job_name,
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
                    job_name=job_name,
                    terminal_state=terminal,
                    table_spec=table_spec,
                    record_count=expected_count,
                    plan_digest=str(document["planDigest"]),
                    output_digest=str(document["outputDigest"]),
                    bundle_digest=bundle.digest,
                    approval_digest=str(document["approvalDigest"]),
                    policy_digest=str(document["policyDigest"]),
                )
            )
    except CloudExecutionRejected:
        raise
    except Exception:
        _reject("cloud_verification")

    sources = tuple(results)
    if tuple(result.source_id for result in sources) != SOURCE_ORDER:
        _reject("cloud_incomplete")
    audit_digest = _audit_digest(
        prepared.run_id, prepared.portfolio_digest, sources
    )
    try:
        observed_audit_digest = warehouse.ensure_portfolio_audit(
            run_id=prepared.run_id,
            portfolio_digest=prepared.portfolio_digest,
            audit_digest=audit_digest,
            sources=sources,
        )
    except Exception:
        _reject("cloud_audit")
    if observed_audit_digest != audit_digest:
        _reject("cloud_audit_binding")
    return CloudPortfolioResult(
        run_id=prepared.run_id,
        portfolio_digest=prepared.portfolio_digest,
        audit_digest=audit_digest,
        sources=sources,
    )
