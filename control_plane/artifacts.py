"""Build contract-ready edge handoff artifacts without exposing legacy values."""

from __future__ import annotations

import dataclasses
import math
import re
from datetime import datetime

from control_plane.canonical import (
    SCHEMA_VERSION,
    canonical_json_bytes,
    document_digest,
    require_digest,
    require_run_id,
    sha256_digest,
    stable_id,
)
from edge_runtime.types import DecodedSource, SourcePayload, get_source_spec
from edge_security.local_gemma_agent import LocalGemmaReview
from edge_security.pii_redactor import (
    PII_CATEGORIES,
    DeterministicRedaction,
    SanitizedSource,
)


_RECORD_SET = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")
_RECORD_ID = re.compile(r"^rec_[A-Za-z0-9]{8,64}$")
_GEMMA_MODEL = re.compile(r"^gemma-[A-Za-z0-9._-]{2,64}$")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class ArtifactBuildError(ValueError):
    """Fail-closed artifact error whose message never contains record values."""


@dataclasses.dataclass(frozen=True)
class EdgeArtifacts:
    """The three public handoff documents produced inside the edge boundary."""

    source_manifest: dict[str, object] = dataclasses.field(repr=False)
    record_batch: dict[str, object] = dataclasses.field(repr=False)
    redaction_report: dict[str, object] = dataclasses.field(repr=False)


def _fail(reason: str) -> ArtifactBuildError:
    return ArtifactBuildError(f"edge artifact validation failed: {reason}")


def _require_timestamp(value: str) -> str:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise _fail("invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise _fail("invalid timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _fail("invalid timestamp")
    return value


def _scalar_type(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        if not math.isfinite(value):
            raise _fail("unsupported scalar")
        return "number"
    if type(value) is str:
        return "string"
    raise _fail("unsupported scalar")


def _schema_descriptor(decoded: DecodedSource) -> list[dict[str, str]]:
    expected: list[dict[str, str]] | None = None
    ordinals: set[int] = set()
    for record in decoded.records:
        if record.ordinal in ordinals:
            raise _fail("duplicate record ordinal")
        ordinals.add(record.ordinal)
        descriptor = []
        for field in record.fields:
            if _FIELD_NAME.fullmatch(field.name) is None:
                raise _fail("invalid field metadata")
            descriptor.append(
                {
                    "name": field.name,
                    "category": field.category,
                    "scalarType": _scalar_type(field.value),
                }
            )
        if expected is None:
            expected = descriptor
        elif descriptor != expected:
            raise _fail("inconsistent record schema")
    if expected is None:
        raise _fail("missing decoded records")
    return expected


def _require_category_counts(
    counts: object, *, expected: dict[str, int]
) -> dict[str, int]:
    if not isinstance(counts, dict) or set(counts) != set(PII_CATEGORIES):
        raise _fail("invalid category counts")
    normalized: dict[str, int] = {}
    for category in PII_CATEGORIES:
        count = counts.get(category)
        if type(count) is not int or count < 0:
            raise _fail("invalid category counts")
        normalized[category] = count
    if normalized != expected:
        raise _fail("inconsistent category counts")
    return normalized


def _validate_sanitized_output(
    decoded: DecodedSource,
    deterministic: DeterministicRedaction,
) -> tuple[dict[str, object], dict[str, int]]:
    sanitized = deterministic.sanitized
    if not isinstance(sanitized, SanitizedSource):
        raise _fail("missing deterministic output")
    if (
        sanitized.source_id != decoded.source_id
        or sanitized.record_set != decoded.record_set
        or len(sanitized.records) != len(decoded.records)
    ):
        raise _fail("inconsistent deterministic output")

    expected_counts = {category: 0 for category in PII_CATEGORIES}
    record_ids: set[str] = set()
    for decoded_record, protected_record in zip(decoded.records, sanitized.records):
        if (
            protected_record.ordinal != decoded_record.ordinal
            or len(protected_record.fields) != len(decoded_record.fields)
            or _RECORD_ID.fullmatch(protected_record.record_id) is None
            or protected_record.record_id in record_ids
        ):
            raise _fail("inconsistent deterministic output")
        record_ids.add(protected_record.record_id)

        for decoded_field, protected_field in zip(
            decoded_record.fields, protected_record.fields
        ):
            if protected_field.name != decoded_field.name:
                raise _fail("inconsistent deterministic output")
            if decoded_field.category == "public":
                if (
                    protected_field.protection != "sanitized"
                    or _scalar_type(protected_field.value)
                    != _scalar_type(decoded_field.value)
                    or protected_field.value != decoded_field.value
                ):
                    raise _fail("inconsistent deterministic output")
            else:
                expected_counts[decoded_field.category] += 1
                if (
                    protected_field.protection != "tokenized"
                    or not isinstance(protected_field.value, str)
                    or re.fullmatch(r"tok_[A-Za-z0-9_-]{8,256}", protected_field.value)
                    is None
                ):
                    raise _fail("inconsistent deterministic output")

    category_counts = _require_category_counts(
        deterministic.category_counts,
        expected=expected_counts,
    )
    if (
        type(deterministic.finding_count) is not int
        or deterministic.finding_count != sum(category_counts.values())
    ):
        raise _fail("inconsistent deterministic findings")
    try:
        require_digest(deterministic.evidence_digest)
    except (TypeError, ValueError):
        raise _fail("invalid deterministic evidence") from None

    candidate = sanitized.as_candidate()
    if (
        set(candidate) != {"sourceId", "recordSet", "records"}
        or candidate["sourceId"] != decoded.source_id
        or candidate["recordSet"] != decoded.record_set
        or not isinstance(candidate["records"], list)
        or len(candidate["records"]) != len(decoded.records)
    ):
        raise _fail("inconsistent deterministic candidate")
    return candidate, category_counts


def _validate_gemma_review(review: LocalGemmaReview) -> dict[str, int]:
    if not isinstance(review, LocalGemmaReview):
        raise _fail("missing local Gemma review")
    if (
        review.status != "passed"
        or review.execution_location != "edge-local"
        or _GEMMA_MODEL.fullmatch(review.model) is None
        or review.finding_count != 0
        or bool(review.findings)
    ):
        raise _fail("local Gemma review did not pass")
    try:
        require_digest(review.evidence_digest)
    except (TypeError, ValueError):
        raise _fail("invalid local Gemma evidence") from None
    return {category: 0 for category in PII_CATEGORIES}


def build_edge_artifacts(
    *,
    run_id: str,
    observed_at: str,
    payload: SourcePayload,
    decoded: DecodedSource,
    deterministic: DeterministicRedaction,
    gemma_review: LocalGemmaReview,
) -> EdgeArtifacts:
    """Build one source's manifest, sanitized batch, and passing report.

    The function accepts only an internally consistent, successfully protected
    source. Any failed or ambiguous state is rejected without including record
    data in the exception.
    """

    try:
        require_run_id(run_id)
    except (TypeError, ValueError):
        raise _fail("invalid run ID") from None
    observed_at = _require_timestamp(observed_at)
    if not isinstance(payload, SourcePayload) or not isinstance(decoded, DecodedSource):
        raise _fail("invalid edge input")
    if type(payload.data) is not bytes:
        raise _fail("invalid source payload")
    try:
        canonical_spec = get_source_spec(payload.spec.source_id)
    except (AttributeError, ValueError):
        raise _fail("invalid source specification") from None
    if payload.spec != canonical_spec or decoded.source_id != payload.spec.source_id:
        raise _fail("cross-source mismatch")
    if _RECORD_SET.fullmatch(decoded.record_set) is None:
        raise _fail("invalid record set")

    descriptor = _schema_descriptor(decoded)
    schema_digest = sha256_digest(canonical_json_bytes(descriptor))
    candidate, deterministic_counts = _validate_sanitized_output(
        decoded, deterministic
    )
    gemma_counts = _validate_gemma_review(gemma_review)

    inventory_digest = sha256_digest(payload.data)
    manifest_id = stable_id(
        "manifest_",
        run_id,
        decoded.source_id,
        inventory_digest,
        decoded.record_set,
        schema_digest,
        observed_at,
    )
    source_manifest: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "manifestId": manifest_id,
        "runId": run_id,
        "sourceId": decoded.source_id,
        "hostname": payload.spec.hostname,
        "inventoryDigest": inventory_digest,
        "recordSets": [
            {
                "name": decoded.record_set,
                "recordCount": len(decoded.records),
                "byteCount": payload.size_bytes,
                "schemaDigest": schema_digest,
            }
        ],
        "observedAt": observed_at,
    }
    manifest_digest = document_digest(source_manifest)

    records = candidate["records"]
    record_batch: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "batchId": stable_id(
            "batch_", run_id, decoded.source_id, manifest_digest, schema_digest
        ),
        "runId": run_id,
        "sourceId": decoded.source_id,
        "sourceManifestDigest": manifest_digest,
        "recordSet": decoded.record_set,
        "schemaDigest": schema_digest,
        "recordCount": len(records),
        "records": records,
    }

    redaction_report: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "reportId": stable_id(
            "report_",
            run_id,
            decoded.source_id,
            manifest_digest,
            deterministic.evidence_digest,
            gemma_review.evidence_digest,
        ),
        "runId": run_id,
        "sourceId": decoded.source_id,
        "sourceManifestDigest": manifest_digest,
        "deterministicCheck": {
            "engine": "deterministic-pii-rules",
            "rulesetVersion": "1.0.0",
            "status": "passed",
            "findingCount": deterministic.finding_count,
            "categoryCounts": deterministic_counts,
            "evidenceDigest": deterministic.evidence_digest,
        },
        "localGemmaCheck": {
            "model": gemma_review.model,
            "executionLocation": gemma_review.execution_location,
            "status": "passed",
            "findingCount": 0,
            "categoryCounts": gemma_counts,
            "evidenceDigest": gemma_review.evidence_digest,
        },
        "unresolvedFindingCount": 0,
        "status": "passed",
        "failClosed": True,
        "completedAt": observed_at,
    }
    redaction_report["reportDigest"] = document_digest(
        redaction_report, omit=("reportDigest",)
    )
    return EdgeArtifacts(source_manifest, record_batch, redaction_report)
