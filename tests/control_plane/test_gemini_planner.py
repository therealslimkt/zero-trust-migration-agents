from __future__ import annotations

import copy
import json
import unittest

from control_plane.canonical import SOURCE_ORDER, document_digest
from control_plane.gemini_planner import (
    MAX_MODEL_RESPONSE_BYTES,
    GeminiPlanCompiler,
    PlanCompilationError,
)


RUN_ID = "mig_123456789012"
ZERO_COUNTS = {
    "name": 0,
    "email": 0,
    "phone": 0,
    "address": 0,
    "governmentId": 0,
    "financialAccount": 0,
    "other": 0,
}


def artifacts():
    result = {}
    for source_id in SOURCE_ORDER:
        record_set = {"jde": "F0101", "maxdb": "KNA1", "btrieve": "ARCUS_CUSTOMER"}[
            source_id
        ]
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
                    "byteCount": 10,
                    "schemaDigest": "sha256:" + "2" * 64,
                }
            ],
            "observedAt": "2026-08-26T21:00:00Z",
        }
        manifest_digest = document_digest(manifest)
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
        result[source_id] = {
            "source_manifest": manifest,
            "record_batch": {
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
                        "recordId": "rec_12345678",
                        "ordinal": 0,
                        "values": [
                            {
                                "field": "customer_token",
                                "protection": "tokenized",
                                "value": "tok_SafeToken1234",
                            }
                        ],
                    }
                ],
            },
            "redaction_report": report,
        }
    return result


def valid_draft():
    return {
        "plans": [
            {
                "sourceId": source_id,
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
            for source_id in reversed(SOURCE_ORDER)
        ]
    }


class RecordingModel:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __call__(self, request):
        self.calls.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class GeminiPlanCompilerTests(unittest.IsolatedAsyncioTestCase):
    async def test_compiles_three_contract_plans_in_deterministic_order(self):
        model = RecordingModel(valid_draft())
        compiler = GeminiPlanCompiler(model, "gemini-3.5-flash")

        portfolio = await compiler.compile(RUN_ID, artifacts())

        self.assertEqual([plan["sourceId"] for plan in portfolio.plans], list(SOURCE_ORDER))
        self.assertTrue(portfolio.portfolio_digest.startswith("sha256:"))
        self.assertEqual(portfolio.model, "gemini-3.5-flash")
        for plan in portfolio.as_documents():
            self.assertEqual(plan["target"]["table"], {
                "jde": "jde_f0101",
                "maxdb": "sap_kna1",
                "btrieve": "accpac_arcus",
            }[plan["sourceId"]])
            self.assertEqual(
                plan["planDigest"], document_digest(plan, omit=("planDigest",))
            )
        self.assertNotIn("tok_SafeToken1234", repr(portfolio))
        with self.assertRaises(TypeError):
            portfolio.plans[0]["sourceId"] = "maxdb"
        self.assertEqual(len(model.calls), 1)

    async def test_digests_are_stable_when_model_order_changes(self):
        first = await GeminiPlanCompiler(
            RecordingModel(valid_draft()), "gemini-3.5-flash"
        ).compile(RUN_ID, artifacts())
        reordered = valid_draft()
        reordered["plans"].reverse()
        second = await GeminiPlanCompiler(
            RecordingModel(reordered), "gemini-3.5-flash"
        ).compile(RUN_ID, artifacts())
        self.assertEqual(first.portfolio_digest, second.portfolio_digest)

    async def test_preflight_failures_do_not_call_model(self):
        variants = []
        missing = artifacts()
        del missing["jde"]
        variants.append(missing)
        failed = artifacts()
        failed["maxdb"]["redaction_report"]["status"] = "blocked"
        variants.append(failed)
        mismatch = artifacts()
        mismatch["btrieve"]["record_batch"]["sourceManifestDigest"] = "sha256:" + "9" * 64
        variants.append(mismatch)
        counts = artifacts()
        counts["jde"]["record_batch"]["recordCount"] = 2
        variants.append(counts)
        forbidden = artifacts()
        forbidden["jde"]["record_batch"]["raw"] = "DO_NOT_ECHO"
        variants.append(forbidden)

        for value in variants:
            model = RecordingModel(valid_draft())
            with self.subTest(value=list(value)):
                with self.assertRaises(PlanCompilationError) as caught:
                    await GeminiPlanCompiler(model, "gemini-3.5-flash").compile(
                        RUN_ID, value
                    )
                self.assertEqual(model.calls, [])
                self.assertNotIn("DO_NOT_ECHO", str(caught.exception))

    async def test_rejects_malformed_oversized_and_non_json_responses(self):
        responses = (
            "{bad",
            " " * (MAX_MODEL_RESPONSE_BYTES + 1),
            {"plans": [], "extra": True},
            {"plans": {"not": "a list"}},
            object(),
        )
        for response in responses:
            with self.subTest(kind=type(response).__name__):
                with self.assertRaises(PlanCompilationError):
                    await GeminiPlanCompiler(
                        RecordingModel(response), "gemini-3.5-flash"
                    ).compile(RUN_ID, artifacts())

    async def test_rejects_duplicate_unknown_and_executable_plan_fields(self):
        duplicate = valid_draft()
        duplicate["plans"][1]["sourceId"] = duplicate["plans"][0]["sourceId"]
        unknown = valid_draft()
        unknown["plans"][0]["target"] = {"dataset": "attacker"}
        executable = valid_draft()
        executable["plans"][0]["operations"] = [{"code": "DO_NOT_ECHO"}]
        invalid_operation = valid_draft()
        invalid_operation["plans"][0]["operations"] = [
            {"operation": "shell", "field": "customer_token"}
        ]

        for response in (duplicate, unknown, executable, invalid_operation):
            with self.subTest(response=response["plans"][0]["sourceId"]):
                with self.assertRaises(PlanCompilationError) as caught:
                    await GeminiPlanCompiler(
                        RecordingModel(response), "gemini-3.5-flash"
                    ).compile(RUN_ID, artifacts())
                self.assertNotIn("DO_NOT_ECHO", str(caught.exception))

    async def test_rejects_edge_only_and_field_inconsistent_plans(self):
        edge_only = valid_draft()
        edge_only["plans"][0]["operations"] = [
            {
                "operation": "tokenize",
                "field": "customer_token",
                "outputField": "customer_id",
                "algorithm": "hmac-sha256",
                "keyReference": "secret://migration/key",
                "tokenFormat": "base64url",
            }
        ]
        missing = valid_draft()
        missing["plans"][0]["operations"][0]["from"] = "absent"
        overwrite = valid_draft()
        overwrite["plans"][0]["operations"][0]["to"] = "customer_token"
        wrong_output = valid_draft()
        wrong_output["plans"][0]["outputFields"][0]["name"] = "not_produced"

        for response in (edge_only, missing, overwrite, wrong_output):
            with self.subTest(operation=response["plans"][0]["operations"][0]):
                with self.assertRaises(PlanCompilationError):
                    await GeminiPlanCompiler(
                        RecordingModel(response), "gemini-3.5-flash"
                    ).compile(RUN_ID, artifacts())

    async def test_rejects_duplicate_and_noncontiguous_batch_identity(self):
        variants = []
        duplicate_field = artifacts()
        duplicate_field["jde"]["record_batch"]["records"][0]["values"].append(
            copy.deepcopy(
                duplicate_field["jde"]["record_batch"]["records"][0]["values"][0]
            )
        )
        variants.append(duplicate_field)
        wrong_ordinal = artifacts()
        wrong_ordinal["maxdb"]["record_batch"]["records"][0]["ordinal"] = 4
        variants.append(wrong_ordinal)

        for value in variants:
            model = RecordingModel(valid_draft())
            with self.assertRaises(PlanCompilationError):
                await GeminiPlanCompiler(model, "gemini-3.5-flash").compile(
                    RUN_ID, value
                )
            self.assertEqual(model.calls, [])

    async def test_model_exception_is_suppressed(self):
        with self.assertRaises(PlanCompilationError) as caught:
            await GeminiPlanCompiler(
                RecordingModel(RuntimeError("DO_NOT_ECHO")),
                "gemini-3.5-flash",
            ).compile(RUN_ID, artifacts())
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("DO_NOT_ECHO", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
