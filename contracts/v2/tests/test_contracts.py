from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Any


V2_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = V2_ROOT.parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "tests" / "contracts"))

from schema_tools import ContractValidationError, ContractValidator  # noqa: E402


TOOL_SPEC = importlib.util.spec_from_file_location(
    "v2_verify_contracts", V2_ROOT / "tools" / "verify_contracts.py"
)
assert TOOL_SPEC and TOOL_SPEC.loader
VERIFY = importlib.util.module_from_spec(TOOL_SPEC)
TOOL_SPEC.loader.exec_module(VERIFY)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def walk(node: Any, pointer: str = "$"):
    if isinstance(node, dict):
        yield pointer, node
        for key, value in node.items():
            yield from walk(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{pointer}/{index}")


def split_schema_ref(schema_ref: str) -> tuple[Path, str]:
    document, separator, fragment = schema_ref.partition("#")
    return V2_ROOT / document, (f"#{fragment}" if separator else "")


def validate(instance: Any, schema_ref: str) -> None:
    schema_path, fragment = split_schema_ref(schema_ref)
    validator = ContractValidator(schema_path)
    if not fragment:
        validator.validate(instance)
        return
    schema, resolved_path = validator.resolve_ref(fragment, schema_path)
    validator._validate(instance, schema, resolved_path, "$")


class V2SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_json(V2_ROOT / "manifest.json")

    def test_schemas_are_draft_2020_12_and_object_boundaries_are_closed(self):
        for relative_path in self.manifest["schemas"]:
            schema = load_json(V2_ROOT / relative_path)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            for pointer, node in walk(schema):
                if node.get("type") == "object":
                    with self.subTest(schema=relative_path, pointer=pointer):
                        self.assertIs(node.get("additionalProperties"), False)

    def test_all_schema_references_resolve_locally(self):
        for relative_path in self.manifest["schemas"]:
            schema_path = V2_ROOT / relative_path
            validator = ContractValidator(schema_path)
            for pointer, node in walk(load_json(schema_path)):
                if "$ref" in node:
                    with self.subTest(schema=relative_path, pointer=pointer):
                        _, resolved = validator.resolve_ref(node["$ref"], schema_path)
                        resolved.relative_to((V2_ROOT / "schemas").resolve())

    def test_valid_examples_validate(self):
        for item in self.manifest["examples"]["valid"]:
            with self.subTest(example=item["path"]):
                validate(load_json(V2_ROOT / item["path"]), item["schema"])

    def test_negative_fixture_descriptors_are_closed_and_precise(self):
        for item in self.manifest["examples"]["invalid"]:
            case = load_json(V2_ROOT / item["path"])
            validate(case, "schemas/invalid-case.schema.json")
            base = load_json(V2_ROOT / "examples" / case["base"])
            mutated = VERIFY.apply_mutation(base, case["mutation"])
            if case["expect"] == "schema_rejection":
                with self.subTest(example=item["path"]):
                    with self.assertRaises(ContractValidationError):
                        validate(mutated, case["targetSchema"])
            else:
                validate(mutated, case["targetSchema"])
                self.assertFalse(VERIFY.embedded_digest_matches(mutated, "cartridgeDigest"))

    def test_manifest_is_complete_and_content_addressed(self):
        VERIFY.verify_manifest()
        listed = set(VERIFY.listed_files(self.manifest))
        discovered = {
            path.relative_to(V2_ROOT).as_posix()
            for directory in (V2_ROOT / "schemas", V2_ROOT / "examples")
            for path in directory.rglob("*.json")
        }
        discovered.add("openapi.json")
        self.assertEqual(listed, discovered)


class V2PolicyTests(unittest.TestCase):
    def test_openapi_has_only_the_three_orchestration_routes(self):
        document = load_json(V2_ROOT / "openapi.json")
        self.assertEqual(
            set(document["paths"]),
            {
                "/api/v2/runs/{run_id}/orchestration",
                "/api/v2/runs/{run_id}/events",
                "/api/v2/runs/{run_id}/inputs/{interrupt_id}",
            },
        )
        self.assertNotIn("approval", " ".join(document["paths"]))
        self.assertIn("x-approval-endpoints", document)

    def test_input_body_cannot_represent_approval(self):
        operations = load_json(V2_ROOT / "schemas" / "operations.schema.json")
        body = operations["$defs"]["resumeInterruptRequest"]
        self.assertEqual(body["properties"]["kind"]["enum"], ["clarification", "task_input"])
        self.assertTrue({"actor", "decision", "approval", "authorization"}.isdisjoint(body["properties"]))

    def test_frozen_agent_and_component_roles_are_disjoint(self):
        common = load_json(V2_ROOT / "schemas" / "common.schema.json")["$defs"]
        product_agents = set(common["productAgentId"]["enum"])
        self.assertEqual(
            product_agents,
            {
                "atlas", "scout", "source_analyst_sap", "source_analyst_jde",
                "source_analyst_oracle", "source_analyst_cobol", "source_analyst_ibmi",
                "source_analyst_sage", "source_analyst_ax", "maven", "prisma",
                "jetty_advisor",
            },
        )
        deterministic = set(common["deterministicComponentId"]["enum"])
        self.assertEqual(deterministic, {"vale", "flow", "ledger", "forge"})
        self.assertTrue(product_agents.isdisjoint(deterministic))
        self.assertTrue(deterministic.isdisjoint(common["agentId"]["enum"]))

    def test_runtime_bounds_and_truthful_labels_are_exact(self):
        common = load_json(V2_ROOT / "schemas" / "common.schema.json")["$defs"]
        budget = common["orchestrationBudget"]["properties"]
        self.assertEqual(budget["maxConcurrentNodes"]["maximum"], 4)
        self.assertEqual(budget["maxModelCalls"]["maximum"], 30)
        self.assertEqual(budget["maxDepth"]["maximum"], 2)
        self.assertEqual(budget["maxRetriesPerNode"]["maximum"], 3)
        task_schema = load_json(V2_ROOT / "schemas" / "task-envelope.schema.json")
        self.assertEqual(task_schema["properties"]["sourceInstanceIds"]["maxItems"], 7)
        self.assertEqual(common["readinessLabel"]["enum"], ["fixture", "cloud", "customer_runtime", "production"])
        self.assertEqual(common["distributionLabel"]["enum"], ["preview_plugin", "production_signed"])

    def test_deterministic_execution_cannot_claim_model_call(self):
        trace = load_json(V2_ROOT / "examples" / "orchestration-trace.graph.json")
        trace["nodeExecutions"][0]["modelCall"] = True
        with self.assertRaises(ContractValidationError):
            validate(trace, "schemas/orchestration.schema.json#/$defs/orchestrationTrace")


if __name__ == "__main__":
    unittest.main()
