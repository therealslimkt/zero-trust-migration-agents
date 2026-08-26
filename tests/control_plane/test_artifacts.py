from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from control_plane.artifacts import ArtifactBuildError, build_edge_artifacts
from control_plane.canonical import document_digest, sha256_digest
from edge_runtime.types import (
    DecodedField,
    DecodedRecord,
    DecodedSource,
    SourcePayload,
    SourceSpec,
    get_source_spec,
)
from edge_security.local_gemma_agent import LocalGemmaReview, ResidualFinding
from edge_security.pii_redactor import DeterministicRedactor, PII_CATEGORIES


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "contracts" / "schemas"
RECORD_SETS = {"jde": "F0101", "maxdb": "KNA1", "btrieve": "ARCUS"}
RUN_ID = "mig_ARTIFACTTEST01"
OBSERVED_AT = "2026-08-26T16:45:30Z"


def load_validator(name: str) -> Draft202012Validator:
    with (SCHEMA_DIR / "common.schema.json").open(encoding="utf-8") as handle:
        common = json.load(handle)
    with (SCHEMA_DIR / name).open(encoding="utf-8") as handle:
        schema = json.load(handle)
    registry = Registry().with_resource(
        common["$id"], Resource.from_contents(common)
    )
    return Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    )


VALIDATORS = {
    "source_manifest": load_validator("source-manifest.schema.json"),
    "record_batch": load_validator("record-batch.schema.json"),
    "redaction_report": load_validator("redaction-report.schema.json"),
}


class EdgeArtifactTests(unittest.TestCase):
    def make_inputs(
        self,
        source_id: str = "jde",
        *,
        public_prefix: str = "PUBLIC",
        payload_data: bytes | None = None,
    ):
        decoded = DecodedSource(
            source_id,
            RECORD_SETS[source_id],
            (
                DecodedRecord(
                    0,
                    (
                        DecodedField("customer_number", 1001, "public"),
                        DecodedField("display_code", f"{public_prefix}-A", "public"),
                        DecodedField("customer_name", "Synthetic Alpha", "name"),
                        DecodedField("active", True, "public"),
                        DecodedField("credit_limit", 15.5, "public"),
                        DecodedField("optional_code", None, "public"),
                    ),
                ),
                DecodedRecord(
                    1,
                    (
                        DecodedField("customer_number", 1002, "public"),
                        DecodedField("display_code", f"{public_prefix}-B", "public"),
                        DecodedField("customer_name", "Synthetic Beta", "name"),
                        DecodedField("active", False, "public"),
                        DecodedField("credit_limit", 22.75, "public"),
                        DecodedField("optional_code", None, "public"),
                    ),
                ),
            ),
        )
        payload = SourcePayload(
            get_source_spec(source_id),
            payload_data if payload_data is not None else b"synthetic-" + source_id.encode(),
        )
        deterministic = DeterministicRedactor(b"k" * 32).sanitize(decoded)
        gemma = LocalGemmaReview(
            status="passed",
            findings=(),
            evidence_digest=sha256_digest(b"edge-local-gemma-verdict"),
        )
        return payload, decoded, deterministic, gemma

    def build(self, source_id: str = "jde", **overrides):
        payload, decoded, deterministic, gemma = self.make_inputs(source_id)
        arguments = {
            "run_id": RUN_ID,
            "observed_at": OBSERVED_AT,
            "payload": payload,
            "decoded": decoded,
            "deterministic": deterministic,
            "gemma_review": gemma,
        }
        arguments.update(overrides)
        return build_edge_artifacts(**arguments)

    def test_all_three_sources_build_schema_valid_artifacts(self):
        for source_id in ("jde", "maxdb", "btrieve"):
            with self.subTest(source_id=source_id):
                artifacts = self.build(source_id)
                VALIDATORS["source_manifest"].validate(artifacts.source_manifest)
                VALIDATORS["record_batch"].validate(artifacts.record_batch)
                VALIDATORS["redaction_report"].validate(
                    artifacts.redaction_report
                )

    def test_reference_counts_and_report_digest_are_integral(self):
        payload, decoded, deterministic, gemma = self.make_inputs("maxdb")
        artifacts = build_edge_artifacts(
            run_id=RUN_ID,
            observed_at=OBSERVED_AT,
            payload=payload,
            decoded=decoded,
            deterministic=deterministic,
            gemma_review=gemma,
        )
        manifest = artifacts.source_manifest
        batch = artifacts.record_batch
        report = artifacts.redaction_report
        manifest_digest = document_digest(manifest)

        self.assertEqual(manifest["inventoryDigest"], sha256_digest(payload.data))
        self.assertEqual(manifest["recordSets"][0]["recordCount"], len(decoded.records))
        self.assertEqual(manifest["recordSets"][0]["byteCount"], len(payload.data))
        self.assertEqual(batch["records"], deterministic.sanitized.as_candidate()["records"])
        self.assertEqual(batch["recordCount"], len(decoded.records))
        self.assertEqual(batch["sourceManifestDigest"], manifest_digest)
        self.assertEqual(report["sourceManifestDigest"], manifest_digest)
        self.assertEqual(
            report["reportDigest"],
            document_digest(report, omit=("reportDigest",)),
        )
        self.assertEqual(
            batch["schemaDigest"], manifest["recordSets"][0]["schemaDigest"]
        )
        self.assertEqual(
            set(report["deterministicCheck"]["categoryCounts"]),
            set(PII_CATEGORIES),
        )
        self.assertEqual(
            set(report["localGemmaCheck"]["categoryCounts"]),
            set(PII_CATEGORIES),
        )

    def test_identical_inputs_are_deterministic(self):
        first_inputs = self.make_inputs("btrieve")
        second_inputs = self.make_inputs("btrieve")
        first = build_edge_artifacts(
            run_id=RUN_ID,
            observed_at=OBSERVED_AT,
            payload=first_inputs[0],
            decoded=first_inputs[1],
            deterministic=first_inputs[2],
            gemma_review=first_inputs[3],
        )
        second = build_edge_artifacts(
            run_id=RUN_ID,
            observed_at=OBSERVED_AT,
            payload=second_inputs[0],
            decoded=second_inputs[1],
            deterministic=second_inputs[2],
            gemma_review=second_inputs[3],
        )
        self.assertEqual(first, second)

    def test_returned_documents_are_detached_from_the_digest_anchor(self):
        artifacts = self.build("jde")
        original_manifest = artifacts.source_manifest
        original_digest = document_digest(original_manifest)

        original_manifest["hostname"] = "changed-after-build"

        self.assertNotEqual(original_manifest, artifacts.source_manifest)
        self.assertEqual(original_digest, document_digest(artifacts.source_manifest))
        self.assertEqual(
            artifacts.record_batch["sourceManifestDigest"], original_digest
        )

    def test_record_ordinals_must_be_contiguous_and_ordered(self):
        payload, decoded, _, gemma = self.make_inputs("jde")
        for ordinals in ((0, 2), (1, 0), (0, 0)):
            records = tuple(
                dataclasses.replace(record, ordinal=ordinal)
                for record, ordinal in zip(decoded.records, ordinals)
            )
            changed = dataclasses.replace(decoded, records=records)
            deterministic = DeterministicRedactor(b"k" * 32).sanitize(changed)
            with self.subTest(ordinals=ordinals):
                with self.assertRaisesRegex(ArtifactBuildError, "contiguous"):
                    build_edge_artifacts(
                        run_id=RUN_ID,
                        observed_at=OBSERVED_AT,
                        payload=payload,
                        decoded=changed,
                        deterministic=deterministic,
                        gemma_review=gemma,
                    )

    def test_schema_digest_never_depends_on_field_values(self):
        first = self.make_inputs("jde", public_prefix="FIRST", payload_data=b"same")
        second = self.make_inputs("jde", public_prefix="SECOND", payload_data=b"same")
        first_artifacts = build_edge_artifacts(
            run_id=RUN_ID,
            observed_at=OBSERVED_AT,
            payload=first[0],
            decoded=first[1],
            deterministic=first[2],
            gemma_review=first[3],
        )
        second_artifacts = build_edge_artifacts(
            run_id=RUN_ID,
            observed_at=OBSERVED_AT,
            payload=second[0],
            decoded=second[1],
            deterministic=second[2],
            gemma_review=second[3],
        )
        self.assertEqual(
            first_artifacts.record_batch["schemaDigest"],
            second_artifacts.record_batch["schemaDigest"],
        )
        self.assertNotEqual(
            first_artifacts.record_batch["records"],
            second_artifacts.record_batch["records"],
        )

    def test_cross_source_mismatch_is_rejected(self):
        payload, _, _, _ = self.make_inputs("jde")
        _, decoded, deterministic, gemma = self.make_inputs("maxdb")
        with self.assertRaisesRegex(ArtifactBuildError, "cross-source mismatch"):
            build_edge_artifacts(
                run_id=RUN_ID,
                observed_at=OBSERVED_AT,
                payload=payload,
                decoded=decoded,
                deterministic=deterministic,
                gemma_review=gemma,
            )

    def test_noncanonical_source_spec_is_rejected(self):
        payload, decoded, deterministic, gemma = self.make_inputs("jde")
        forged_payload = SourcePayload(
            SourceSpec("jde", "legacy-maxdb", payload.spec.remote_path, payload.spec.source_format),
            payload.data,
        )
        with self.assertRaises(ArtifactBuildError):
            self.build(
                payload=forged_payload,
                decoded=decoded,
                deterministic=deterministic,
                gemma_review=gemma,
            )

    def test_record_set_and_count_mismatches_are_rejected(self):
        payload, decoded, deterministic, gemma = self.make_inputs("jde")
        wrong_set = dataclasses.replace(
            deterministic,
            sanitized=dataclasses.replace(
                deterministic.sanitized, record_set="OTHER"
            ),
        )
        short_output = dataclasses.replace(
            deterministic,
            sanitized=dataclasses.replace(
                deterministic.sanitized,
                records=deterministic.sanitized.records[:1],
            ),
        )
        for bad in (wrong_set, short_output):
            with self.subTest(bad=bad):
                with self.assertRaises(ArtifactBuildError):
                    build_edge_artifacts(
                        run_id=RUN_ID,
                        observed_at=OBSERVED_AT,
                        payload=payload,
                        decoded=decoded,
                        deterministic=bad,
                        gemma_review=gemma,
                    )

    def test_inconsistent_field_names_categories_order_and_types_are_rejected(self):
        base = (DecodedField("code", "A", "public"), DecodedField("name", "N", "name"))
        variants = (
            (DecodedField("other_code", "B", "public"), DecodedField("name", "M", "name")),
            (DecodedField("code", "B", "public"), DecodedField("name", "M", "email")),
            (DecodedField("name", "M", "name"), DecodedField("code", "B", "public")),
            (DecodedField("code", 2, "public"), DecodedField("name", "M", "name")),
        )
        payload = SourcePayload(get_source_spec("jde"), b"schema-check")
        gemma = LocalGemmaReview("passed", (), sha256_digest(b"gemma"))
        for variant in variants:
            decoded = DecodedSource(
                "jde",
                "F0101",
                (DecodedRecord(0, base), DecodedRecord(1, variant)),
            )
            deterministic = DeterministicRedactor(b"z" * 32).sanitize(decoded)
            with self.subTest(variant=variant):
                with self.assertRaisesRegex(
                    ArtifactBuildError, "inconsistent record schema"
                ):
                    build_edge_artifacts(
                        run_id=RUN_ID,
                        observed_at=OBSERVED_AT,
                        payload=payload,
                        decoded=decoded,
                        deterministic=deterministic,
                        gemma_review=gemma,
                    )

    def test_deterministic_count_state_must_be_exact(self):
        payload, decoded, deterministic, gemma = self.make_inputs("jde")
        missing_category = dict(deterministic.category_counts)
        missing_category.pop("other")
        bad_states = (
            dataclasses.replace(deterministic, category_counts=missing_category),
            dataclasses.replace(
                deterministic,
                finding_count=deterministic.finding_count + 1,
            ),
            dataclasses.replace(
                deterministic,
                category_counts={category: 0 for category in PII_CATEGORIES},
            ),
        )
        for bad in bad_states:
            with self.subTest(bad=bad):
                with self.assertRaises(ArtifactBuildError):
                    build_edge_artifacts(
                        run_id=RUN_ID,
                        observed_at=OBSERVED_AT,
                        payload=payload,
                        decoded=decoded,
                        deterministic=bad,
                        gemma_review=gemma,
                    )

    def test_gemma_blocked_error_and_inconsistent_states_fail_closed(self):
        payload, decoded, deterministic, _ = self.make_inputs("jde")
        finding = ResidualFinding("display_code", "other")
        digest = sha256_digest(b"gemma-state")
        reviews = (
            LocalGemmaReview("blocked", (finding,), digest),
            LocalGemmaReview("error", (), digest),
            LocalGemmaReview("passed", (finding,), digest),
            LocalGemmaReview("blocked", (), digest),
        )
        for review in reviews:
            with self.subTest(status=review.status, findings=review.finding_count):
                with self.assertRaisesRegex(
                    ArtifactBuildError, "local Gemma review did not pass"
                ):
                    build_edge_artifacts(
                        run_id=RUN_ID,
                        observed_at=OBSERVED_AT,
                        payload=payload,
                        decoded=decoded,
                        deterministic=deterministic,
                        gemma_review=review,
                    )

    def test_malformed_run_ids_and_timestamps_are_rejected(self):
        bad_run_ids = ("run_short", "mig_short", "mig_has-a-hyphen")
        bad_timestamps = (
            "2026-08-26",
            "2026-08-26T16:45:30",
            "2026-13-26T16:45:30Z",
            "not-a-time",
        )
        for run_id in bad_run_ids:
            with self.subTest(run_id=run_id):
                with self.assertRaises(ArtifactBuildError):
                    self.build(run_id=run_id)
        for observed_at in bad_timestamps:
            with self.subTest(observed_at=observed_at):
                with self.assertRaises(ArtifactBuildError):
                    self.build(observed_at=observed_at)

    def test_repr_and_error_messages_never_expose_values(self):
        secret = "SENSITIVE_DECODED_VALUE"
        payload, decoded, deterministic, gemma = self.make_inputs(
            "jde", public_prefix=secret, payload_data=secret.encode()
        )
        artifacts = build_edge_artifacts(
            run_id=RUN_ID,
            observed_at=OBSERVED_AT,
            payload=payload,
            decoded=decoded,
            deterministic=deterministic,
            gemma_review=gemma,
        )
        for value in (payload, decoded, deterministic, artifacts):
            self.assertNotIn(secret, repr(value))

        _, other_decoded, other_deterministic, _ = self.make_inputs("maxdb")
        with self.assertRaises(ArtifactBuildError) as raised:
            build_edge_artifacts(
                run_id=RUN_ID,
                observed_at=OBSERVED_AT,
                payload=payload,
                decoded=other_decoded,
                deterministic=other_deterministic,
                gemma_review=gemma,
            )
        self.assertNotIn(secret, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
