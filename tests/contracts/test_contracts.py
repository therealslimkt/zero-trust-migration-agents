from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from schema_tools import ContractValidationError, ContractValidator


ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"
EXAMPLES = ROOT / "contracts" / "examples"
OPENAPI = ROOT / "contracts" / "openapi.json"


POSITIVE_EXAMPLES = {
    "create-migration.json": "migration-request.schema.json",
    "migration-run.json": "migration-run.schema.json",
    "source-manifest-jde.json": "source-manifest.schema.json",
    "source-manifest-maxdb.json": "source-manifest.schema.json",
    "source-manifest-btrieve.json": "source-manifest.schema.json",
    "record-batch-jde.json": "record-batch.schema.json",
    "record-batch-maxdb.json": "record-batch.schema.json",
    "record-batch-btrieve.json": "record-batch.schema.json",
    "redaction-report-jde.json": "redaction-report.schema.json",
    "redaction-report-maxdb.json": "redaction-report.schema.json",
    "redaction-report-btrieve.json": "redaction-report.schema.json",
    "transform-plan-jde.json": "transform-plan.schema.json",
    "transform-plan-maxdb.json": "transform-plan.schema.json",
    "transform-plan-btrieve.json": "transform-plan.schema.json",
    "approval-request.json": "approval-request.schema.json",
    "approval-response.json": "approval-response.schema.json",
    "source-event.json": "sse-event.schema.json",
    "portfolio-event.json": "sse-event.schema.json",
}

NEGATIVE_EXAMPLES = {
    "ip-hostname.migration-request.invalid.json": "migration-request.schema.json",
    "ip-hostname.source-manifest.invalid.json": "source-manifest.schema.json",
    "raw-pii.migration-request.invalid.json": "migration-request.schema.json",
    "raw-pii.record-batch.invalid.json": "record-batch.schema.json",
    "unknown.redaction-report.invalid.json": "redaction-report.schema.json",
    "code.transform-plan.invalid.json": "transform-plan.schema.json",
    "script.transform-plan.invalid.json": "transform-plan.schema.json",
    "command.transform-plan.invalid.json": "transform-plan.schema.json",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def walk_schema(node: Any, pointer: str = "$"):
    if isinstance(node, dict):
        yield pointer, node
        for key, value in node.items():
            yield from walk_schema(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_schema(value, f"{pointer}/{index}")


class SchemaStructureTests(unittest.TestCase):
    def test_every_schema_parses_and_declares_draft(self):
        schema_paths = sorted(SCHEMAS.glob("*.schema.json"))
        self.assertGreater(len(schema_paths), 0)
        for path in schema_paths:
            with self.subTest(path=path.name):
                schema = load_json(path)
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_every_object_trust_boundary_is_closed(self):
        for path in sorted(SCHEMAS.glob("*.schema.json")):
            schema = load_json(path)
            for pointer, node in walk_schema(schema):
                if node.get("type") == "object":
                    with self.subTest(path=path.name, pointer=pointer):
                        self.assertIs(node.get("additionalProperties"), False)

    def test_all_schema_references_resolve_locally(self):
        for path in sorted(SCHEMAS.glob("*.schema.json")):
            validator = ContractValidator(path)
            for pointer, node in walk_schema(load_json(path)):
                if "$ref" in node:
                    with self.subTest(path=path.name, pointer=pointer):
                        validator.resolve_ref(node["$ref"], path)

    def test_canonical_source_and_state_values_are_exact(self):
        common = load_json(SCHEMAS / "common.schema.json")
        self.assertEqual(common["$defs"]["sourceId"]["enum"], ["jde", "maxdb", "btrieve"])
        self.assertEqual(
            common["$defs"]["sourceDescriptor"]["properties"]["hostname"]["enum"],
            ["legacy-jde-db", "legacy-maxdb", "legacy-btrieve-db"],
        )
        self.assertEqual(
            common["$defs"]["runState"]["enum"],
            [
                "created", "inventorying", "redacting", "planning",
                "awaiting_approval", "approved", "executing", "verifying",
                "completed", "failed", "cancelled",
            ],
        )

    def test_transform_operations_are_closed_and_declarative(self):
        schema = load_json(SCHEMAS / "transform-plan.schema.json")
        refs = schema["$defs"]["operation"]["oneOf"]
        names = set()
        for ref in refs:
            definition_name = ref["$ref"].split("/")[-1]
            definition = schema["$defs"][definition_name]
            self.assertIs(definition["additionalProperties"], False)
            names.add(definition["properties"]["operation"]["const"])
        self.assertEqual(
            names,
            {"decode_text", "packed_decimal", "map_date", "rename", "cast", "drop", "tokenize"},
        )
        for _, node in walk_schema(schema):
            properties = node.get("properties", {})
            self.assertTrue({"code", "script", "command", "expression"}.isdisjoint(properties))


class ExampleValidationTests(unittest.TestCase):
    def test_positive_examples_validate(self):
        for example_name, schema_name in POSITIVE_EXAMPLES.items():
            with self.subTest(example=example_name):
                ContractValidator(SCHEMAS / schema_name).validate(load_json(EXAMPLES / example_name))

    def test_forbidden_examples_are_rejected(self):
        invalid_dir = EXAMPLES / "invalid"
        for example_name, schema_name in NEGATIVE_EXAMPLES.items():
            with self.subTest(example=example_name):
                with self.assertRaises(ContractValidationError):
                    ContractValidator(SCHEMAS / schema_name).validate(load_json(invalid_dir / example_name))

    def test_approval_digest_is_required(self):
        request = load_json(EXAMPLES / "approval-request.json")
        request.pop("planDigest")
        with self.assertRaises(ContractValidationError):
            ContractValidator(SCHEMAS / "approval-request.schema.json").validate(request)

    def test_source_id_is_present_only_for_source_events(self):
        validator = ContractValidator(SCHEMAS / "sse-event.schema.json")
        source_event = load_json(EXAMPLES / "source-event.json")
        source_event.pop("sourceId")
        with self.assertRaises(ContractValidationError):
            validator.validate(source_event)

        portfolio_event = load_json(EXAMPLES / "portfolio-event.json")
        portfolio_event["sourceId"] = "jde"
        with self.assertRaises(ContractValidationError):
            validator.validate(portfolio_event)

    def test_record_batches_allow_only_sanitized_or_tokenized_values(self):
        batch = load_json(EXAMPLES / "record-batch-jde.json")
        batch["records"][0]["values"][0]["protection"] = "raw"
        with self.assertRaises(ContractValidationError):
            ContractValidator(SCHEMAS / "record-batch.schema.json").validate(batch)

    def test_redaction_reports_fail_closed(self):
        report = load_json(EXAMPLES / "redaction-report-jde.json")
        report["unresolvedFindingCount"] = 1
        with self.assertRaises(ContractValidationError):
            ContractValidator(SCHEMAS / "redaction-report.schema.json").validate(report)

        report = load_json(EXAMPLES / "redaction-report-jde.json")
        report["failClosed"] = False
        with self.assertRaises(ContractValidationError):
            ContractValidator(SCHEMAS / "redaction-report.schema.json").validate(report)

        report = load_json(EXAMPLES / "redaction-report-jde.json")
        report["localGemmaCheck"]["status"] = "error"
        with self.assertRaises(ContractValidationError):
            ContractValidator(SCHEMAS / "redaction-report.schema.json").validate(report)


class OpenApiTests(unittest.TestCase):
    def setUp(self):
        self.document = load_json(OPENAPI)

    def test_public_routes_are_exact(self):
        self.assertEqual(
            set(self.document["paths"]),
            {
                "/api/v1/migrations",
                "/api/v1/migrations/{run_id}",
                "/api/v1/migrations/{run_id}/events",
                "/api/v1/migrations/{run_id}/approval",
            },
        )

    def test_openapi_references_canonical_schemas(self):
        external_refs = set()
        for pointer, node in walk_schema(self.document):
            ref = node.get("$ref")
            if ref and not ref.startswith("#"):
                external_refs.add(ref)
                document_ref = ref.partition("#")[0]
                target = (OPENAPI.parent / document_ref).resolve()
                with self.subTest(pointer=pointer, ref=ref):
                    self.assertTrue(target.is_file())
        self.assertTrue(
            {
                "./schemas/migration-request.schema.json",
                "./schemas/migration-run.schema.json",
                "./schemas/approval-request.schema.json",
                "./schemas/approval-response.schema.json",
                "./schemas/sse-event.schema.json",
            }.issubset(external_refs)
        )

    def test_events_are_text_event_stream_with_event_schema(self):
        response = self.document["paths"]["/api/v1/migrations/{run_id}/events"]["get"]["responses"]["200"]
        media = response["content"]["text/event-stream"]
        self.assertEqual(media["schema"], {"type": "string"})
        self.assertEqual(media["x-sse-data-schema"]["$ref"], "./schemas/sse-event.schema.json")

    def test_manifest_lists_standalone_milestone_two_contracts(self):
        manifest = load_json(ROOT / "contracts" / "manifest.json")
        self.assertTrue(
            {
                "schemas/source-manifest.schema.json",
                "schemas/record-batch.schema.json",
                "schemas/redaction-report.schema.json",
            }.issubset(manifest["schemas"])
        )


if __name__ == "__main__":
    unittest.main()
