from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_IDS = ["jde", "maxdb", "btrieve"]
HOSTNAMES = {
    "jde": "legacy-jde-db",
    "maxdb": "legacy-maxdb",
    "btrieve": "legacy-btrieve-db",
}
DOMAIN_OPERATIONS = {
    "/api/v1/migrations": {"post"},
    "/api/v1/migrations/{run_id}": {"get"},
    "/api/v1/migrations/{run_id}/events": {"get"},
    "/api/v1/migrations/{run_id}/approval": {"post"},
}
WEB_OPERATIONS = {
    "/api/web/v1/session": {"get"},
    "/api/web/v1/demos": {"get"},
    "/api/web/v1/demos/{demo_id}": {"get"},
    "/api/web/v1/demo-bundles/{bundle_digest}": {"get"},
    "/api/web/v1/demo-publications": {"post"},
    "/api/web/v1/runs": {"get", "post"},
    "/api/web/v1/runs/{run_id}": {"get"},
    "/api/web/v1/runs/{run_id}/sources/{source_id}": {"get"},
    "/api/web/v1/runs/{run_id}/sources/{source_id}/terminal": {"get"},
    "/api/web/v1/runs/{run_id}/events": {"get"},
    "/api/web/v1/runs/{run_id}/approval": {"post"},
    "/api/web/v1/cloud/connection": {"get"},
    "/api/web/v1/cloud/connection/setup": {"post"},
    "/api/web/v1/cloud/connection/verify": {"post"},
    "/api/web/v1/drivers/research": {"post"},
    "/api/web/v1/drivers/research/{research_id}": {"get"},
    "/api/web/v1/drivers/research/{research_id}/approval": {"post"},
}


def load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def operations(document: dict) -> dict[str, set[str]]:
    return {
        path: {method for method in item if method != "parameters"}
        for path, item in document["paths"].items()
    }


def assigned_literal(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"missing literal assignment {name}")


class V1CompatibilityTest(unittest.TestCase):
    def test_contract_versions_and_source_identity_are_frozen(self) -> None:
        domain_manifest = load_json("contracts/manifest.json")
        web_manifest = load_json("contracts/web/v1/manifest.json")
        domain_common = load_json("contracts/schemas/common.schema.json")
        web_common = load_json("contracts/web/v1/schemas/common.schema.json")

        self.assertEqual(domain_manifest["contractVersion"], "1.0.0")
        self.assertEqual(web_manifest["contractVersion"], "1.0.0")
        self.assertEqual(domain_common["$defs"]["schemaVersion"]["const"], "1.0.0")
        self.assertEqual(web_common["$defs"]["schemaVersion"]["const"], "1.0.0")
        self.assertEqual(domain_common["$defs"]["sourceId"]["enum"], SOURCE_IDS)
        self.assertEqual(web_common["$defs"]["sourceId"]["enum"], SOURCE_IDS)
        self.assertEqual(
            domain_common["$defs"]["sourceDescriptor"]["properties"]["hostname"]["enum"],
            list(HOSTNAMES.values()),
        )

    def test_domain_and_browser_v1_operations_are_exact(self) -> None:
        domain = load_json("contracts/openapi.json")
        web = load_json("contracts/web/v1/openapi.json")

        self.assertEqual(operations(domain), DOMAIN_OPERATIONS)
        self.assertEqual(operations(web), WEB_OPERATIONS)
        self.assertFalse(any(path.startswith("/api/v2") for path in domain["paths"]))
        self.assertFalse(any(path.startswith("/api/v2") for path in web["paths"]))

    def test_v1_entry_point_keeps_three_sources_and_approval_stop(self) -> None:
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="main.py")
        profiles = assigned_literal(tree, "SANITIZED_SOURCE_PROFILES")

        self.assertEqual([profile["sourceId"] for profile in profiles], SOURCE_IDS)
        self.assertEqual(
            {profile["sourceId"]: profile["hostname"] for profile in profiles},
            HOSTNAMES,
        )
        orchestrator = next(
            node
            for node in tree.body
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "run_orchestrator"
        )
        string_literals = {
            node.value
            for node in ast.walk(orchestrator)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("awaiting_approval", string_literals)
        self.assertNotIn("completed", string_literals)
        self.assertNotIn("executing", string_literals)


if __name__ == "__main__":
    unittest.main()
