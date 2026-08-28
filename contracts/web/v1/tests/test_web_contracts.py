from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
OPENAPI = ROOT / "openapi.json"
MANIFEST = ROOT / "manifest.json"
EXPECTED_REQUIREMENTS_SHA = "37374d4fb13c4fd890e60c07b7d691fec0fe34ac5440b878aa275e5d9f3c0191"


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


def resolve_ref(ref: str, base: Path) -> Any:
    document_ref, _, fragment = ref.partition("#")
    path = (base.parent / document_ref).resolve() if document_ref else base
    target = load_json(path)
    if fragment:
        if not fragment.startswith("/"):
            raise AssertionError(f"unsupported JSON pointer: {ref}")
        for raw in fragment[1:].split("/"):
            key = raw.replace("~1", "/").replace("~0", "~")
            target = target[int(key)] if isinstance(target, list) else target[key]
    return target


class WebSchemaTests(unittest.TestCase):
    def test_manifest_records_frozen_requirements_and_schema_inventory(self):
        manifest = load_json(MANIFEST)
        self.assertEqual(manifest["contractVersion"], "1.0.0")
        self.assertEqual(manifest["requirementsSha256"], EXPECTED_REQUIREMENTS_SHA)
        self.assertEqual(
            set(manifest["schemas"]),
            {
                "schemas/common.schema.json",
                "schemas/demo-manifest.schema.json",
                "schemas/operations.schema.json",
            },
        )

    def test_every_schema_is_draft_2020_12_and_every_object_boundary_is_closed(self):
        for path in sorted(SCHEMAS.glob("*.schema.json")):
            schema = load_json(path)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            for pointer, node in walk(schema):
                if node.get("type") == "object":
                    with self.subTest(path=path.name, pointer=pointer):
                        self.assertIs(node.get("additionalProperties"), False)

    def test_all_local_schema_references_resolve(self):
        for path in [*sorted(SCHEMAS.glob("*.schema.json")), OPENAPI]:
            for pointer, node in walk(load_json(path)):
                ref = node.get("$ref")
                if ref:
                    with self.subTest(path=path.name, pointer=pointer, ref=ref):
                        self.assertIsNotNone(resolve_ref(ref, path))

    def test_demo_manifest_is_recorded_completed_synthetic_only(self):
        schema = load_json(SCHEMAS / "demo-manifest.schema.json")
        properties = schema["properties"]
        self.assertEqual(properties["experienceMode"], {"const": "recorded_demo"})
        self.assertEqual(properties["dataClass"], {"const": "synthetic_demo"})
        self.assertEqual(properties["runState"], {"const": "completed"})
        self.assertEqual(schema["required"], list(dict.fromkeys(schema["required"])))

    def test_manifest_contains_actual_three_pane_replay_shapes(self):
        schema = load_json(SCHEMAS / "demo-manifest.schema.json")
        definitions = schema["$defs"]
        self.assertTrue({"sourceSystem", "compiler", "destination"}.issubset(definitions))
        self.assertIn("rawBytesHex", definitions["sourceSample"]["required"])
        self.assertTrue(
            {
                "actions", "transforms", "driver", "localGemmaEvidence",
                "geminiVertexEvidence", "beamTransformIds", "dataflowJobId", "approval",
            }.issubset(definitions["compiler"]["required"])
        )
        self.assertTrue(
            {"rows", "schema", "reconciliation", "dataflowEvidence", "bigQueryEvidence"}.issubset(
                definitions["destination"]["required"]
            )
        )

    def test_create_run_is_exactly_the_canonical_three_sources(self):
        operations = load_json(SCHEMAS / "operations.schema.json")
        sources = operations["$defs"]["createLiveRunRequest"]["properties"]["sources"]
        self.assertEqual((sources["minItems"], sources["maxItems"]), (3, 3))
        self.assertTrue(sources["uniqueItems"])
        self.assertEqual(
            {rule["contains"]["const"] for rule in sources["allOf"]},
            {"jde", "maxdb", "btrieve"},
        )

    def test_async_research_and_manual_upload_states_are_explicit(self):
        operations = load_json(SCHEMAS / "operations.schema.json")["$defs"]
        research = operations["driverResearchStatusResponse"]
        self.assertEqual(
            research["properties"]["status"]["enum"],
            ["queued", "running", "completed", "failed"],
        )
        approval = operations["driverApprovalResponse"]
        self.assertNotIn("artifactFingerprint", approval["required"])
        self.assertEqual(
            approval["properties"]["status"]["enum"],
            ["pending_upload", "retrieving", "verified"],
        )

    def test_terminal_frame_is_closed_typed_and_safe_single_line(self):
        common = load_json(SCHEMAS / "common.schema.json")
        terminal = common["$defs"]["terminalFrame"]
        self.assertIs(terminal["additionalProperties"], False)
        self.assertEqual(
            set(terminal["required"]),
            {
                "schemaVersion", "frameId", "runId", "sourceId", "globalSequence",
                "laneSequence", "timestamp", "lane", "stream", "producer", "tool",
                "line", "severity", "evidenceReferences",
            },
        )
        self.assertEqual(terminal["properties"]["lane"]["enum"], ["source", "edge", "compiler", "destination"])
        self.assertEqual(terminal["properties"]["stream"]["enum"], ["command", "stdout", "stderr", "system", "metric"])
        self.assertEqual(terminal["properties"]["severity"]["enum"], ["debug", "info", "warning", "error"])
        self.assertEqual(terminal["properties"]["line"]["maxLength"], 4096)
        self.assertIn("\\u001F", terminal["properties"]["line"]["pattern"])
        source = load_json(SCHEMAS / "demo-manifest.schema.json")["$defs"]["sourceReplay"]
        self.assertIn("terminalFrames", source["required"])
        self.assertEqual(source["properties"]["terminalFrames"]["minItems"], 1)


class WebOpenAPITests(unittest.TestCase):
    def setUp(self):
        self.document = load_json(OPENAPI)

    def test_routes_use_separate_api_web_v1_prefix(self):
        paths = set(self.document["paths"])
        self.assertGreater(len(paths), 0)
        self.assertTrue(all(path.startswith("/api/web/v1/") for path in paths))
        self.assertFalse(any(path.startswith("/api/v1/") for path in paths))

    def test_public_surface_is_read_only_and_exact(self):
        public = {
            path
            for path, operations in self.document["paths"].items()
            for method, operation in operations.items()
            if method in {"get", "post", "put", "patch", "delete"} and operation.get("security") == []
        }
        self.assertEqual(
            public,
            {
                "/api/web/v1/demos",
                "/api/web/v1/demos/{demo_id}",
                "/api/web/v1/demo-bundles/{bundle_digest}",
            },
        )
        for path in public:
            self.assertEqual(set(self.document["paths"][path]), {"get"})

    def test_live_approval_cannot_accept_a_browser_actor(self):
        operations = load_json(SCHEMAS / "operations.schema.json")
        approval = operations["$defs"]["liveApprovalRequest"]
        self.assertNotIn("decidedBy", approval["properties"])
        self.assertNotIn("actor", approval["properties"])
        self.assertIs(approval["additionalProperties"], False)
        create = operations["$defs"]["createLiveRunRequest"]
        self.assertNotIn("requestedBy", create["properties"])
        self.assertNotIn("owner", create["properties"])

    def test_practice_approval_has_no_http_operation(self):
        operation_ids = {
            operation["operationId"]
            for methods in self.document["paths"].values()
            for method, operation in methods.items()
            if method in {"get", "post", "put", "patch", "delete"}
        }
        self.assertFalse(any("practice" in operation_id.lower() for operation_id in operation_ids))

    def test_bootstrap_stream_cloud_and_research_poll_routes_exist(self):
        paths = self.document["paths"]
        self.assertIn("/api/web/v1/session", paths)
        self.assertIn("/api/web/v1/runs/{run_id}/events", paths)
        self.assertIn("/api/web/v1/cloud/connection", paths)
        self.assertIn("/api/web/v1/drivers/research/{research_id}", paths)
        stream = paths["/api/web/v1/runs/{run_id}/events"]["get"]
        parameter_refs = {parameter["$ref"] for parameter in stream["parameters"]}
        self.assertIn("#/components/parameters/LastEventId", parameter_refs)

    def test_terminal_stream_is_authenticated_resumable_and_typed(self):
        path = "/api/web/v1/runs/{run_id}/sources/{source_id}/terminal"
        stream = self.document["paths"][path]["get"]
        self.assertEqual(stream["security"], [{"identityToken": []}])
        self.assertEqual(
            {parameter["$ref"] for parameter in stream["parameters"]},
            {"#/components/parameters/RunId", "#/components/parameters/SourceId", "#/components/parameters/LastTerminalFrameId"},
        )
        sse = stream["responses"]["200"]["content"]["text/event-stream"]
        self.assertEqual(sse["x-sse-event"], "terminal.frame")
        self.assertEqual(sse["x-sse-data-schema"]["$ref"], "./schemas/operations.schema.json#/$defs/terminalFrame")

    def test_publication_body_cap_is_eight_mib(self):
        publication = self.document["paths"]["/api/web/v1/demo-publications"]["post"]
        self.assertEqual(publication["x-max-body-bytes"], 8 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
