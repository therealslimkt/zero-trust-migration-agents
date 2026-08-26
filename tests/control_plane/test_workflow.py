from __future__ import annotations

import copy
import dataclasses
import json
import unittest
from unittest import mock

from control_plane.artifacts import EdgeArtifacts
from control_plane.canonical import (
    SOURCE_ORDER,
    TARGET_TABLES,
    canonical_json_bytes,
    document_digest,
    portfolio_plan_digest,
)
from control_plane.gemini_planner import GeminiPlanCompiler, PortfolioPlan
from control_plane.workflow import (
    PortfolioWorkflowError,
    PreparedPortfolio,
    execute_portfolio,
    prepare_portfolio,
)
from trusted_runtime import execute_plan
from ztm_security.approval import ApprovalRecord


RUN_ID = "mig_WORKFLOW00001"
SENTINEL = "tok_SENTINELPROTECTED987"
ZERO_COUNTS = {
    "name": 0,
    "email": 0,
    "phone": 0,
    "address": 0,
    "governmentId": 0,
    "financialAccount": 0,
    "other": 0,
}


def _documents(source_id: str) -> dict[str, dict[str, object]]:
    record_set = {
        "jde": "F0101",
        "maxdb": "KNA1",
        "btrieve": "ARCUS_CUSTOMER",
    }[source_id]
    manifest = {
        "schemaVersion": "1.0.0",
        "manifestId": "manifest_" + source_id.upper() + "000000000000",
        "runId": RUN_ID,
        "sourceId": source_id,
        "hostname": {
            "jde": "legacy-jde-db",
            "maxdb": "legacy-maxdb",
            "btrieve": "legacy-btrieve-db",
        }[source_id],
        "inventoryDigest": "sha256:" + "1" * 64,
        "recordSets": [
            {
                "name": record_set,
                "recordCount": 1,
                "byteCount": 64,
                "schemaDigest": "sha256:" + "2" * 64,
            }
        ],
        "observedAt": "2026-08-26T21:00:00Z",
    }
    manifest_digest = document_digest(manifest)
    batch = {
        "schemaVersion": "1.0.0",
        "batchId": "batch_" + source_id.upper() + "00000000000000",
        "runId": RUN_ID,
        "sourceId": source_id,
        "sourceManifestDigest": manifest_digest,
        "recordSet": record_set,
        "schemaDigest": "sha256:" + "2" * 64,
        "recordCount": 1,
        "records": [
            {
                "recordId": "rec_" + source_id.upper() + "00000001",
                "ordinal": 0,
                "values": [
                    {
                        "field": "customer_token",
                        "protection": "tokenized",
                        "value": SENTINEL,
                    }
                ],
            }
        ],
    }
    report = {
        "schemaVersion": "1.0.0",
        "reportId": "report_" + source_id.upper() + "000000000000",
        "runId": RUN_ID,
        "sourceId": source_id,
        "sourceManifestDigest": manifest_digest,
        "deterministicCheck": {
            "engine": "deterministic-pii-rules",
            "rulesetVersion": "1.0.0",
            "status": "passed",
            "findingCount": 1,
            "categoryCounts": dict(ZERO_COUNTS),
            "evidenceDigest": "sha256:" + "3" * 64,
        },
        "localGemmaCheck": {
            "model": "gemma-2-2b",
            "executionLocation": "edge-local",
            "status": "passed",
            "findingCount": 0,
            "categoryCounts": dict(ZERO_COUNTS),
            "evidenceDigest": "sha256:" + "4" * 64,
        },
        "unresolvedFindingCount": 0,
        "status": "passed",
        "failClosed": True,
        "completedAt": "2026-08-26T21:00:01Z",
    }
    report["reportDigest"] = document_digest(report, omit=("reportDigest",))
    return {
        "source_manifest": manifest,
        "record_batch": batch,
        "redaction_report": report,
    }


def _artifacts(
    mutator=None,
) -> dict[str, EdgeArtifacts]:
    result = {}
    for source_id in SOURCE_ORDER:
        documents = _documents(source_id)
        if mutator is not None:
            mutator(source_id, documents)
        result[source_id] = EdgeArtifacts(**documents)
    return result


def _plans(
    run_id: str,
    artifacts: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    plans = []
    for source_id in reversed(SOURCE_ORDER):
        manifest = artifacts[source_id]["source_manifest"]
        plan = {
            "schemaVersion": "1.0.0",
            "planId": "plan_" + source_id.upper() + "00000000000000",
            "runId": run_id,
            "sourceId": source_id,
            "sourceManifestDigest": document_digest(manifest),
            "target": {
                "dataset": "legacy_migration",
                "table": TARGET_TABLES[source_id],
            },
            "operations": [
                {
                    "operation": "rename",
                    "from": "customer_token",
                    "to": "customer_id",
                }
            ],
            "outputFields": [
                {"name": "customer_id", "type": "string", "nullable": False}
            ],
        }
        plan["planDigest"] = document_digest(plan, omit=("planDigest",))
        plans.append(plan)
    return plans


class FakeCompiler:
    def __init__(self, mutate=None, *, reported_digest=None, failure=None):
        self.mutate = mutate
        self.reported_digest = reported_digest
        self.failure = failure
        self.calls = []
        self.returned_plans = None

    async def compile(self, run_id, artifacts):
        self.calls.append((run_id, copy.deepcopy(artifacts)))
        if self.failure is not None:
            raise self.failure
        plans = _plans(run_id, artifacts)
        if self.mutate is not None:
            self.mutate(plans, artifacts)
        self.returned_plans = plans
        try:
            actual_digest = portfolio_plan_digest(plans)
        except ValueError:
            actual_digest = "sha256:" + "5" * 64
        return PortfolioPlan(
            tuple(plans),
            self.reported_digest or actual_digest,
            "gemini-test",
        )


def _approval(prepared, *, digest=None, run_id=None):
    return ApprovalRecord(
        approver="portfolio-reviewer",
        plan_digest=digest or prepared.portfolio_digest,
        timestamp="2026-08-26T22:00:00Z",
        portfolio_run_id=run_id or prepared.run_id,
    )


class PortfolioWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.compiler = FakeCompiler()
        self.prepared = await prepare_portfolio(
            artifacts_by_source=_artifacts(), compiler=self.compiler
        )

    async def test_happy_path_is_one_compile_and_three_ordered_executions(self):
        observed = []

        def recording_executor(**kwargs):
            observed.append(kwargs["plan"]["sourceId"])
            return execute_plan(**kwargs)

        with mock.patch(
            "control_plane.workflow.trusted_runtime.execute_plan",
            side_effect=recording_executor,
        ):
            result = execute_portfolio(
                prepared=self.prepared, approval=_approval(self.prepared)
            )

        self.assertEqual(len(self.compiler.calls), 1)
        self.assertEqual(observed, list(SOURCE_ORDER))
        self.assertEqual(
            [item.source_id for item in result.reconciliations], list(SOURCE_ORDER)
        )
        for evidence in result.reconciliations:
            self.assertEqual(evidence.row_count, 1)
            self.assertEqual(evidence.record_count, 1)
            self.assertEqual(
                evidence.target["table"], TARGET_TABLES[evidence.source_id]
            )
            self.assertTrue(evidence.output_digest.startswith("sha256:"))
            self.assertEqual(evidence.rows[0]["customer_id"]["value"], SENTINEL)
        self.assertNotIn(SENTINEL, repr(result))

    async def test_prepared_snapshot_and_output_evidence_resist_mutation(self):
        detached = self.prepared.as_document()
        detached["portfolioDigest"] = "sha256:" + "9" * 64
        detached["sources"][0]["plan"]["sourceId"] = "maxdb"
        plan_copy = self.prepared.plans[0]
        plan_copy["target"]["dataset"] = "caller_mutation"

        result = execute_portfolio(
            prepared=self.prepared, approval=_approval(self.prepared)
        )

        self.assertNotEqual(self.prepared.portfolio_digest, detached["portfolioDigest"])
        self.assertEqual(result.results[0].target["dataset"], "legacy_migration")
        with self.assertRaises(TypeError):
            result.results[0].target["dataset"] = "changed"
        with self.assertRaises(TypeError):
            result.results[0].rows[0]["customer_id"]["value"] = "changed"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.results[0].row_count = 2

    async def test_partial_extra_or_non_artifact_portfolios_are_rejected(self):
        variants = []
        partial = _artifacts()
        del partial["jde"]
        variants.append(partial)
        extra = _artifacts()
        extra["other"] = extra["jde"]
        variants.append(extra)
        wrong_type = _artifacts()
        wrong_type["jde"] = wrong_type["jde"].as_mapping()
        variants.append(wrong_type)

        for value in variants:
            compiler = FakeCompiler()
            with self.subTest(keys=list(value)):
                with self.assertRaisesRegex(
                    PortfolioWorkflowError, "^portfolio artifacts are invalid$"
                ):
                    await prepare_portfolio(
                        artifacts_by_source=value, compiler=compiler
                    )
                self.assertEqual(compiler.calls, [])

    async def test_artifact_run_source_and_manifest_mismatches_are_rejected(self):
        def wrong_run(source_id, documents):
            if source_id == "maxdb":
                documents["record_batch"]["runId"] = "mig_DIFFERENT0001"

        def wrong_source(source_id, documents):
            if source_id == "btrieve":
                documents["record_batch"]["sourceId"] = "jde"

        def wrong_manifest(source_id, documents):
            if source_id == "jde":
                documents["record_batch"]["sourceManifestDigest"] = (
                    "sha256:" + "9" * 64
                )

        for mutator in (wrong_run, wrong_source, wrong_manifest):
            compiler = FakeCompiler()
            with self.assertRaisesRegex(
                PortfolioWorkflowError, "^portfolio artifacts are invalid$"
            ):
                await prepare_portfolio(
                    artifacts_by_source=_artifacts(mutator), compiler=compiler
                )
            self.assertEqual(compiler.calls, [])

    async def test_compiled_plan_bindings_and_recomputed_digests_are_required(self):
        def wrong_run(plans, _artifacts):
            plans[0]["runId"] = "mig_DIFFERENT0001"
            plans[0]["planDigest"] = document_digest(
                plans[0], omit=("planDigest",)
            )

        def wrong_source(plans, _artifacts):
            plans[0]["sourceId"] = plans[1]["sourceId"]
            plans[0]["planDigest"] = document_digest(
                plans[0], omit=("planDigest",)
            )

        def wrong_manifest(plans, _artifacts):
            plans[0]["sourceManifestDigest"] = "sha256:" + "8" * 64
            plans[0]["planDigest"] = document_digest(
                plans[0], omit=("planDigest",)
            )

        def stale_plan_digest(plans, _artifacts):
            plans[0]["target"]["dataset"] = "stale"

        compilers = [
            FakeCompiler(wrong_run),
            FakeCompiler(wrong_source),
            FakeCompiler(wrong_manifest),
            FakeCompiler(stale_plan_digest),
            FakeCompiler(reported_digest="sha256:" + "7" * 64),
        ]
        for compiler in compilers:
            with self.assertRaisesRegex(
                PortfolioWorkflowError, "^compiled portfolio is invalid$"
            ):
                await prepare_portfolio(
                    artifacts_by_source=_artifacts(), compiler=compiler
                )
            self.assertEqual(len(compiler.calls), 1)

    async def test_execution_recomputes_snapshot_digest_before_executor(self):
        document = self.prepared.as_document()
        document["sources"][0]["plan"]["target"]["dataset"] = SENTINEL
        corrupted = PreparedPortfolio(canonical_json_bytes(document))

        with mock.patch(
            "control_plane.workflow.trusted_runtime.execute_plan"
        ) as executor:
            with self.assertRaisesRegex(
                PortfolioWorkflowError, "^compiled portfolio is invalid$"
            ) as caught:
                execute_portfolio(
                    prepared=corrupted, approval=_approval(self.prepared)
                )
        executor.assert_not_called()
        self.assertNotIn(SENTINEL, repr(caught.exception))

    async def test_stale_digest_and_wrong_run_approval_precede_record_work(self):
        approvals = (
            _approval(self.prepared, digest="sha256:" + "6" * 64),
            _approval(self.prepared, run_id="mig_DIFFERENT0001"),
        )
        for approval in approvals:
            with mock.patch(
                "control_plane.workflow.trusted_runtime.execute_plan"
            ) as executor:
                with self.assertRaisesRegex(
                    PortfolioWorkflowError, "^portfolio approval was rejected$"
                ):
                    execute_portfolio(prepared=self.prepared, approval=approval)
            executor.assert_not_called()

    async def test_executor_failure_returns_no_partial_result_and_is_safe(self):
        called = []

        def fails_second(**kwargs):
            called.append(kwargs["plan"]["sourceId"])
            if len(called) == 2:
                raise RuntimeError(SENTINEL)
            return execute_plan(**kwargs)

        with mock.patch(
            "control_plane.workflow.trusted_runtime.execute_plan",
            side_effect=fails_second,
        ):
            with self.assertRaisesRegex(
                PortfolioWorkflowError, "^portfolio execution failed$"
            ) as caught:
                execute_portfolio(
                    prepared=self.prepared, approval=_approval(self.prepared)
                )

        self.assertEqual(called, ["jde", "maxdb"])
        self.assertNotIn(SENTINEL, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    async def test_compiler_exception_is_safe(self):
        compiler = FakeCompiler(failure=RuntimeError(SENTINEL))
        with self.assertRaisesRegex(
            PortfolioWorkflowError, "^portfolio preparation failed$"
        ) as caught:
            await prepare_portfolio(
                artifacts_by_source=_artifacts(), compiler=compiler
            )
        self.assertNotIn(SENTINEL, repr(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    async def test_repository_compiler_surfaces_only_its_safe_failure_reason(self):
        async def invalid_model(_request):
            return {"plans": []}

        compiler = GeminiPlanCompiler(invalid_model, "gemini-test")
        with self.assertRaisesRegex(
            PortfolioWorkflowError,
            "^portfolio planning failed: Gemini must return exactly three plans$",
        ) as caught:
            await prepare_portfolio(
                artifacts_by_source=_artifacts(), compiler=compiler
            )
        self.assertNotIn(SENTINEL, repr(caught.exception))
        self.assertIsNone(caught.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
