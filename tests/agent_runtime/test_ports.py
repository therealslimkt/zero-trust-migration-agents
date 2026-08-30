from __future__ import annotations

import math
import unittest

from agent_runtime.ports import (
    ArtifactLocation,
    ContractDocument,
    RuntimeBoundaryError,
    RuntimePorts,
    VersionedDocument,
)

from .fakes import runtime_port_fakes


class RuntimePortTests(unittest.TestCase):
    def test_contract_document_is_deeply_immutable(self):
        source = {"nested": {"items": [1, "two", True, None]}}
        document = ContractDocument("ztm.workflow.v2", source)
        source["nested"] = {"changed": True}

        self.assertEqual(
            tuple(document.payload["nested"]["items"]), (1, "two", True, None)
        )
        with self.assertRaises(TypeError):
            document.payload["other"] = "value"
        with self.assertRaises(TypeError):
            document.payload["nested"]["other"] = "value"

    def test_contract_document_rejects_non_json_and_nonfinite_values(self):
        invalid = (
            {"bytes": b"secret"},
            {"set": {"not-json"}},
            {"nan": math.nan},
            {1: "non-string-key"},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(RuntimeBoundaryError):
                    ContractDocument("ztm.test.v1", payload)

    def test_versioned_document_and_artifact_reference_fail_closed(self):
        document = ContractDocument("ztm.state.v2", {})
        with self.assertRaisesRegex(RuntimeBoundaryError, "state_revision"):
            VersionedDocument(revision=-1, document=document)
        with self.assertRaisesRegex(RuntimeBoundaryError, "artifact_digest"):
            ArtifactLocation(
                uri="gs://bucket/object",
                digest="latest",
                media_type="application/json",
                size_bytes=1,
            )

    def test_all_six_ports_are_required_and_structurally_validated(self):
        ports = runtime_port_fakes()
        self.assertIsInstance(ports, RuntimePorts)
        with self.assertRaisesRegex(TypeError, "runtime_port_executor"):
            RuntimePorts(
                state=ports.state,
                artifacts=ports.artifacts,
                models=ports.models,
                events=ports.events,
                approvals=ports.approvals,
                executor=object(),
            )


if __name__ == "__main__":
    unittest.main()
