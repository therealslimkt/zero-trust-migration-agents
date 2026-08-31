from __future__ import annotations

import copy
import json
import unittest

from cartridge_lab import CartridgePacket, canonical_digest
from cartridge_lab.ax import (
    AX_ARTIFACT_NAMES,
    AX_FIXTURE_ROOT,
    AX_TRANSFORM_SPEC_DIGEST,
    AXIdentity,
    AXPacketError,
    apply_ax_delta,
    load_ax_packet,
    validate_ax_artifacts,
    validate_ax_records,
)


def artifact(name: str) -> object:
    return json.loads((AX_FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8"))


class DynamicsAXPacketTest(unittest.TestCase):
    def test_shared_packet_shape_and_ui_summary_are_stable(self) -> None:
        packet = load_ax_packet()

        self.assertIsInstance(packet, CartridgePacket)
        self.assertEqual(packet.cartridge_id, "dynamics_ax")
        self.assertEqual(packet.readiness, "synthetic_fixture")
        self.assertEqual(tuple(sorted(packet.artifacts)), tuple(sorted(AX_ARTIFACT_NAMES)))
        self.assertEqual(packet.transform_spec_digest, AX_TRANSFORM_SPEC_DIGEST)
        self.assertEqual(
            packet.ui_summary(),
            {
                "cartridgeId": "dynamics_ax",
                "displayName": "Microsoft Dynamics AX",
                "sourceSystem": "microsoft_dynamics_ax",
                "readiness": "synthetic_fixture",
                "packetDigest": "sha256:5ce2bde2f9878e248cb8423d08512703779b28994aebb963f660246c53cfb826",
                "transformSpecDigest": "sha256:7f875b9bfc9fce91f311e2dd60c3172e45ac3a1860f47d979470621248111b80",
                "reconciliationDigest": "sha256:aceccb767cfab01c81d8f8b1c91b4fb70bf45e56c7455be7d55023ecb469b793",
                "snapshotRecords": 6,
                "silverRecords": 6,
                "invalidRecords": 3,
            },
        )

    def test_identity_requires_company_partition_table_and_recid(self) -> None:
        metadata = artifact("metadata")
        indexed = validate_ax_records(artifact("snapshot"), metadata)

        self.assertEqual(len(indexed), 6)
        self.assertIn(
            AXIdentity("SYN01", "synthetic_partition_01", "SyntheticAxPartyBase", 1001),
            indexed,
        )
        self.assertIn(
            AXIdentity("SYN02", "synthetic_partition_01", "SyntheticAxPartyBase", 1001),
            indexed,
        )
        self.assertIn(
            AXIdentity("SYN01", "synthetic_partition_01", "SyntheticAxCustomerDerived", 1001),
            indexed,
        )
        with self.assertRaisesRegex(AXPacketError, "ax_identity_shape"):
            AXIdentity.from_value({"table": "SyntheticAxPartyBase", "recId": 1001})

    def test_watermark_delta_delete_and_inheritance_reconcile(self) -> None:
        metadata = artifact("metadata")
        snapshot = artifact("snapshot")
        delta = artifact("delta")
        silver = artifact("silver")

        self.assertEqual(apply_ax_delta(snapshot, delta, metadata), silver)
        final = validate_ax_records(silver, metadata)
        self.assertNotIn(
            AXIdentity("SYN01", "synthetic_partition_01", "SyntheticAxPartyBase", 1002),
            final,
        )
        self.assertNotIn(
            AXIdentity("SYN01", "synthetic_partition_01", "SyntheticAxCustomerDerived", 1002),
            final,
        )
        inserted_derived = AXIdentity(
            "SYN01", "synthetic_partition_01", "SyntheticAxCustomerDerived", 1003
        )
        inserted_base = AXIdentity("SYN01", "synthetic_partition_01", "SyntheticAxPartyBase", 1003)
        self.assertEqual(
            AXIdentity.from_value(final[inserted_derived]["baseIdentity"]),
            inserted_base,
        )

    def test_manifest_and_reconciliation_digests_are_independently_recomputed(self) -> None:
        packet = load_ax_packet()
        manifest = packet.artifacts["manifest"]
        embedded = manifest["artifactDigests"]

        for name in AX_ARTIFACT_NAMES:
            if name != "manifest":
                self.assertEqual(embedded[name], canonical_digest(artifact(name)))
        reconciliation = packet.artifacts["reconciliation"]
        self.assertEqual(
            reconciliation["countsDigest"], canonical_digest(reconciliation["counts"])
        )
        independently_built_packet = {
            "cartridge_id": packet.cartridge_id,
            "display_name": packet.display_name,
            "source_system": packet.source_system,
            "readiness": packet.readiness,
            "transform_spec_digest": packet.transform_spec_digest,
            "artifacts": packet.artifacts,
        }
        self.assertEqual(packet.digest, canonical_digest(independently_built_packet))

    def test_invalid_orphan_duplicate_and_cross_company_cases_fail_exactly(self) -> None:
        metadata = artifact("metadata")
        cases = artifact("invalid")

        self.assertEqual(
            {case["case"] for case in cases},
            {"orphan_derived", "duplicate_identity", "cross_company_inheritance"},
        )
        for case in cases:
            with self.subTest(case=case["case"]):
                with self.assertRaisesRegex(AXPacketError, case["expectedCode"]):
                    validate_ax_records(case["records"], metadata)

    def test_stale_embedded_digest_and_nonmonotonic_watermark_fail_closed(self) -> None:
        packet = load_ax_packet()
        tampered = copy.deepcopy(packet.artifacts)
        tampered["manifest"]["artifactDigests"]["silver"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(AXPacketError, "ax_artifact_digest_mismatch"):
            validate_ax_artifacts(tampered)

        delta = copy.deepcopy(packet.artifacts["delta"])
        delta[1]["watermark"] = copy.deepcopy(delta[0]["watermark"])
        with self.assertRaisesRegex(AXPacketError, "ax_delta_watermark_order"):
            apply_ax_delta(packet.artifacts["snapshot"], delta, packet.artifacts["metadata"])

    def test_fixture_packet_contains_no_cloud_or_customer_claim(self) -> None:
        fixture_text = "\n".join(
            (AX_FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8")
            for name in AX_ARTIFACT_NAMES
        ).lower()
        self.assertNotIn("bigquery", fixture_text)
        self.assertNotIn("dataflow", fixture_text)
        self.assertNotIn("customer.com", fixture_text)
        self.assertIn("synthetic_fixture", fixture_text)


if __name__ == "__main__":
    unittest.main()
