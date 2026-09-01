from __future__ import annotations

import copy
import decimal
import json

import pytest

from cloud_runtime.bundle import CloudBundleRejected, build_cloud_bundles
from cloud_runtime.dataflow_template import (
    TemplateInputRejected,
    bigquery_schema,
    destination_rows,
    validate_bundle_document,
)
from cloud_runtime.orchestrator import (
    CloudExecutionRejected,
    CloudRuntimeConfig,
    WarehouseObservation,
    execute_cloud_portfolio,
)
from control_plane.canonical import (
    SOURCE_ORDER,
    TARGET_TABLES,
    canonical_json_bytes,
    document_digest,
    portfolio_plan_digest,
    sha256_digest,
)
from control_plane.workflow import (
    PortfolioExecutionResult,
    PreparedPortfolio,
    SourceReconciliation,
)
from ztm_security.approval import ApprovalRecord


RUN_ID = "mig_CLOUDRUNTIME01"


def _fixture():
    sources = []
    reconciliations = []
    for source_id in SOURCE_ORDER:
        plan = {
            "schemaVersion": "1.0.0",
            "planId": f"plan_{source_id.upper()}CLOUDRUNTIME",
            "runId": RUN_ID,
            "sourceId": source_id,
            "sourceManifestDigest": "sha256:" + "1" * 64,
            "target": {
                "dataset": "legacy_migration",
                "table": TARGET_TABLES[source_id],
            },
            "operations": [
                {"operation": "rename", "from": "old", "to": "customer_id"}
            ],
            "outputFields": [
                {"name": "customer_id", "type": "string", "nullable": False}
            ],
        }
        plan["planDigest"] = document_digest(plan)
        rows = (
            {
                "customer_id": {
                    "protection": "tokenized",
                    "value": f"tok_{source_id}Customer0001",
                }
            },
        )
        reconciliations.append(
            SourceReconciliation(
                source_id=source_id,
                target=plan["target"],
                row_count=1,
                output_digest=sha256_digest(canonical_json_bytes(rows)),
                rows=rows,
            )
        )
        sources.append({"sourceId": source_id, "plan": plan})
    portfolio_digest = portfolio_plan_digest([item["plan"] for item in sources])
    prepared = PreparedPortfolio(
        canonical_json_bytes(
            {
                "schemaVersion": "1.0.0",
                "runId": RUN_ID,
                "portfolioDigest": portfolio_digest,
                "model": "gemini-3.5-flash",
                "sources": sources,
            }
        )
    )
    execution = PortfolioExecutionResult(
        run_id=RUN_ID,
        portfolio_digest=portfolio_digest,
        reconciliations=tuple(reconciliations),
    )
    approval = ApprovalRecord(
        approver="human-reviewer",
        plan_digest=portfolio_digest,
        timestamp="2026-08-26T22:00:00Z",
        portfolio_run_id=RUN_ID,
    )
    return prepared, execution, approval


def _bundles():
    prepared, execution, approval = _fixture()
    return build_cloud_bundles(
        prepared=prepared,
        execution=execution,
        approval=approval,
        policy_categories=frozenset(),
    )


def test_bundle_is_deterministic_complete_and_contains_no_raw_envelope():
    first = _bundles()
    second = _bundles()
    assert first == second
    assert tuple(bundle.source_id for bundle in first) == SOURCE_ORDER
    for bundle in first:
        document = bundle.as_document()
        assert bundle.digest == document["bundleDigest"]
        assert bundle.object_name.endswith(bundle.digest.removeprefix("sha256:") + ".json")
        assert document_digest(document, omit=("bundleDigest",)) == bundle.digest
        assert set(document["rows"][0]["customer_id"]) == {"protection", "value"}


def test_bundle_rejects_wrong_approval_policy_and_tampered_output():
    prepared, execution, approval = _fixture()
    wrong = ApprovalRecord(
        approver="human-reviewer",
        plan_digest="sha256:" + "9" * 64,
        timestamp=approval.timestamp,
        portfolio_run_id=RUN_ID,
    )
    with pytest.raises(CloudBundleRejected, match="^cloud_approval$"):
        build_cloud_bundles(
            prepared=prepared,
            execution=execution,
            approval=wrong,
            policy_categories=frozenset(),
        )


def test_bundle_recomputes_portfolio_digest_and_plan_bindings():
    prepared, execution, approval = _fixture()
    document = prepared.as_document()
    document["sources"][0]["plan"]["runId"] = "mig_SUBSTITUTED001"
    substituted = PreparedPortfolio(canonical_json_bytes(document))
    with pytest.raises(CloudBundleRejected, match="^cloud_plan_binding$"):
        build_cloud_bundles(
            prepared=substituted,
            execution=execution,
            approval=approval,
            policy_categories=frozenset(),
        )

    document = prepared.as_document()
    document["portfolioDigest"] = "sha256:" + "0" * 64
    substituted = PreparedPortfolio(canonical_json_bytes(document))
    matching_approval = ApprovalRecord(
        approver=approval.approver,
        plan_digest=document["portfolioDigest"],
        timestamp=approval.timestamp,
        portfolio_run_id=approval.portfolio_run_id,
    )
    substituted_execution = PortfolioExecutionResult(
        run_id=execution.run_id,
        portfolio_digest=document["portfolioDigest"],
        reconciliations=execution.reconciliations,
    )
    with pytest.raises(CloudBundleRejected, match="^cloud_portfolio_digest$"):
        build_cloud_bundles(
            prepared=substituted,
            execution=substituted_execution,
            approval=matching_approval,
            policy_categories=frozenset(),
        )
    with pytest.raises(CloudBundleRejected, match="^cloud_approval$"):
        build_cloud_bundles(
            prepared=prepared,
            execution=execution,
            approval=approval,
            policy_categories={"raw_pii"},
        )

    bad_result = copy.copy(execution.reconciliations[0])
    object.__setattr__(bad_result, "output_digest", "sha256:" + "8" * 64)
    tampered = PortfolioExecutionResult(
        run_id=execution.run_id,
        portfolio_digest=execution.portfolio_digest,
        reconciliations=(bad_result, *execution.reconciliations[1:]),
    )
    with pytest.raises(CloudBundleRejected, match="^cloud_output_digest$"):
        build_cloud_bundles(
            prepared=prepared,
            execution=tampered,
            approval=approval,
            policy_categories=frozenset(),
        )


def test_template_validates_every_binding_and_emits_lineage():
    bundle = _bundles()[0]
    document = bundle.as_document()
    table = "ztm-agent-9049c3:legacy_migration.jde_f0101"
    validated = validate_bundle_document(
        document,
        expected_run_id=RUN_ID,
        expected_source_id="jde",
        expected_portfolio_digest=document["portfolioDigest"],
        expected_plan_digest=document["planDigest"],
        expected_bundle_digest=bundle.digest,
        output_table=table,
    )
    job_name = "ztm-jde-cloudruntime01-123456789abc"
    rows = list(destination_rows(validated, expected_job_name=job_name))
    assert rows == [
        {
            "customer_id": "tok_jdeCustomer0001",
            "_ztm_run_id": RUN_ID,
            "_ztm_source_id": "jde",
            "_ztm_plan_digest": document["planDigest"],
            "_ztm_output_digest": document["outputDigest"],
            "_ztm_bundle_digest": document["bundleDigest"],
            "_ztm_approval_digest": document["approvalDigest"],
            "_ztm_policy_digest": document["policyDigest"],
            "_ztm_job_name": job_name,
            "_ztm_row_ordinal": 0,
        }
    ]
    schema = bigquery_schema(document["outputFields"])
    assert schema["fields"][0] == {
        "name": "customer_id",
        "type": "STRING",
        "mode": "REQUIRED",
    }

    tampered = copy.deepcopy(document)
    tampered["rows"][0]["customer_id"]["value"] = "tok_tampered0001"
    with pytest.raises(TemplateInputRejected, match="digest"):
        validate_bundle_document(
            tampered,
            expected_run_id=RUN_ID,
            expected_source_id="jde",
            expected_portfolio_digest=document["portfolioDigest"],
            expected_plan_digest=document["planDigest"],
            expected_bundle_digest=bundle.digest,
            output_table=table,
        )


class _Store:
    def __init__(self):
        self.calls = []

    def ensure_object(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs["digest"]


class _Dataflow:
    def __init__(self, existing=None, *, job_id_prefix="job"):
        self.launches = []
        self.existing = dict(existing or {})
        self.job_id_prefix = job_id_prefix

    def find_job_by_name(self, **kwargs):
        return self.existing.get(kwargs["job_name"])

    def launch_flex_template(self, **kwargs):
        self.launches.append(kwargs)
        job_id = f"{self.job_id_prefix}-{kwargs['labels']['ztm_source']}-1"
        self.existing[kwargs["job_name"]] = job_id
        return job_id

    def wait_for_terminal(self, **kwargs):
        return "JOB_STATE_DONE"


class _Warehouse:
    def __init__(self, documents, dataflow, *, partial_source=None):
        self.documents = documents
        self.dataflow = dataflow
        self.partial_source = partial_source
        self.calls = []
        self.audit_calls = []

    def ensure_portfolio_audit(self, **kwargs):
        self.audit_calls.append(kwargs)
        return kwargs["audit_digest"]

    def observe_lineage(self, **kwargs):
        self.calls.append(kwargs)
        document = self.documents[kwargs["source_id"]]
        job_names = {
            call["job_name"]
            for call in self.dataflow.launches
            if call["labels"]["ztm_source"] == kwargs["source_id"]
        }
        job_names.update(
            name
            for name in self.dataflow.existing
            if f"ztm-{kwargs['source_id']}-" in name
        )
        if not job_names:
            return WarehouseObservation(
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
        if kwargs["source_id"] == self.partial_source:
            return WarehouseObservation(
                row_count=1,
                distinct_ordinal_count=1,
                minimum_ordinal=0,
                maximum_ordinal=0,
                plan_digests=frozenset({"sha256:" + "f" * 64}),
                output_digests=frozenset({document["outputDigest"]}),
                bundle_digests=frozenset({document["bundleDigest"]}),
                approval_digests=frozenset({document["approvalDigest"]}),
                policy_digests=frozenset({document["policyDigest"]}),
                job_names=frozenset(job_names),
            )
        return WarehouseObservation(
            row_count=document["recordCount"],
            distinct_ordinal_count=document["recordCount"],
            minimum_ordinal=0 if document["recordCount"] else None,
            maximum_ordinal=document["recordCount"] - 1
            if document["recordCount"]
            else None,
            plan_digests=frozenset({document["planDigest"]}),
            output_digests=frozenset({document["outputDigest"]}),
            bundle_digests=frozenset({document["bundleDigest"]}),
            approval_digests=frozenset({document["approvalDigest"]}),
            policy_digests=frozenset({document["policyDigest"]}),
            job_names=frozenset(job_names),
        )


def _config():
    return CloudRuntimeConfig(
        project="ztm-agent-9049c3",
        region="us-central1",
        ingress_bucket="ztm-agent-9049c3-ingress",
        dataset="legacy_migration",
        flex_template_spec_uri="gs://ztm-agent-9049c3-templates/ztm.json",
        worker_service_account="worker@ztm-agent-9049c3.iam.gserviceaccount.com",
        worker_subnetwork="regions/us-central1/subnetworks/ztm-dataflow",
        sdk_container_image=(
            "us-central1-docker.pkg.dev/ztm-agent-9049c3/dataflow/ztm@sha256:"
            + "a" * 64
        ),
    )


def test_orchestrator_uploads_before_launch_and_requires_exact_reconciliation():
    prepared, execution, approval = _fixture()
    bundles = _bundles()
    documents = {bundle.source_id: bundle.as_document() for bundle in bundles}
    store = _Store()
    dataflow = _Dataflow()
    warehouse = _Warehouse(documents, dataflow)
    result = execute_cloud_portfolio(
        prepared=prepared,
        execution=execution,
        approval=approval,
        policy_categories=frozenset(),
        config=_config(),
        object_store=store,
        dataflow=dataflow,
        warehouse=warehouse,
    )
    assert tuple(source.source_id for source in result.sources) == SOURCE_ORDER
    assert len(store.calls) == len(SOURCE_ORDER)
    assert len(dataflow.launches) == len(SOURCE_ORDER)
    assert len(warehouse.calls) == 2 * len(SOURCE_ORDER)
    assert len(warehouse.audit_calls) == 1
    assert result.audit_digest.startswith("sha256:")
    assert all("output_schema_json" in call["parameters"] for call in dataflow.launches)

    documents["dynamics"]["recordCount"] = 2
    with pytest.raises(CloudExecutionRejected, match="^cloud_reconciliation$"):
        execute_cloud_portfolio(
            prepared=prepared,
            execution=execution,
            approval=approval,
            policy_categories=frozenset(),
            config=_config(),
            object_store=_Store(),
            dataflow=_Dataflow(),
            warehouse=_Warehouse(documents, _Dataflow()),
        )


def test_orchestrator_has_no_side_effect_before_approval_passes():
    prepared, execution, approval = _fixture()
    store = _Store()
    wrong = ApprovalRecord(
        approver=approval.approver,
        plan_digest="sha256:" + "9" * 64,
        timestamp=approval.timestamp,
        portfolio_run_id=approval.portfolio_run_id,
    )
    with pytest.raises(CloudExecutionRejected, match="^cloud_preflight$"):
        execute_cloud_portfolio(
            prepared=prepared,
            execution=execution,
            approval=wrong,
            policy_categories=frozenset(),
            config=_config(),
            object_store=store,
            dataflow=_Dataflow(),
            warehouse=_Warehouse({}, _Dataflow()),
        )
    assert store.calls == []


def test_orchestrator_recovers_existing_jobs_without_duplicate_launches():
    prepared, execution, approval = _fixture()
    bundles = _bundles()
    documents = {bundle.source_id: bundle.as_document() for bundle in bundles}
    existing = {
        f"ztm-{bundle.source_id}-cloudruntime01-{bundle.digest[7:19]}":
        f"2026-08-26_17_42_01-{index}"
        for index, bundle in enumerate(bundles, start=1)
    }
    dataflow = _Dataflow(existing)

    result = execute_cloud_portfolio(
        prepared=prepared,
        execution=execution,
        approval=approval,
        policy_categories=frozenset(),
        config=_config(),
        object_store=_Store(),
        dataflow=dataflow,
        warehouse=_Warehouse(documents, dataflow),
    )

    assert dataflow.launches == []
    assert [source.job_id for source in result.sources] == list(existing.values())


def test_orchestrator_rejects_partial_existing_lineage_before_a_new_launch():
    prepared, execution, approval = _fixture()
    bundles = _bundles()
    documents = {bundle.source_id: bundle.as_document() for bundle in bundles}
    existing_name = (
        f"ztm-jde-cloudruntime01-{bundles[0].digest[7:19]}"
    )
    dataflow = _Dataflow({existing_name: "opaque_existing_job_123"})
    warehouse = _Warehouse(documents, dataflow, partial_source="jde")

    with pytest.raises(CloudExecutionRejected, match="^cloud_existing_lineage$"):
        execute_cloud_portfolio(
            prepared=prepared,
            execution=execution,
            approval=approval,
            policy_categories=frozenset(),
            config=_config(),
            object_store=_Store(),
            dataflow=dataflow,
            warehouse=warehouse,
        )
    assert dataflow.launches == []


@pytest.mark.parametrize(
    "declared_type,value",
    [
        ("integer", 2**63),
        ("integer", -(2**63) - 1),
        ("decimal", decimal.Decimal("1e29")),
        ("decimal", decimal.Decimal("0.0000000001")),
    ],
)
def test_bundle_rejects_values_outside_bigquery_numeric_domains(
    declared_type, value
):
    prepared, execution, approval = _fixture()
    document = prepared.as_document()
    document["sources"][0]["plan"]["outputFields"][0]["type"] = declared_type
    plan = document["sources"][0]["plan"]
    plan["planDigest"] = document_digest(plan, omit=("planDigest",))
    document["portfolioDigest"] = portfolio_plan_digest(
        [source["plan"] for source in document["sources"]]
    )
    prepared = PreparedPortfolio(canonical_json_bytes(document))
    reconciliations = list(execution.reconciliations)
    rows = ({"customer_id": {"protection": "sanitized", "value": value}},)
    digest_value = format(value, "f") if isinstance(value, decimal.Decimal) else value
    digest_rows = (
        {"customer_id": {"protection": "sanitized", "value": digest_value}},
    )
    reconciliations[0] = SourceReconciliation(
        source_id="jde",
        target=plan["target"],
        row_count=1,
        output_digest=sha256_digest(canonical_json_bytes(digest_rows)),
        rows=rows,
    )
    execution = PortfolioExecutionResult(
        run_id=prepared.run_id,
        portfolio_digest=prepared.portfolio_digest,
        reconciliations=tuple(reconciliations),
    )
    approval = ApprovalRecord(
        approver=approval.approver,
        plan_digest=prepared.portfolio_digest,
        timestamp=approval.timestamp,
        portfolio_run_id=prepared.run_id,
    )

    with pytest.raises(CloudBundleRejected, match="^cloud_numeric_domain$"):
        build_cloud_bundles(
            prepared=prepared,
            execution=execution,
            approval=approval,
            policy_categories=frozenset(),
        )
