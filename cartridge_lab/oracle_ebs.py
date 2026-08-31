"""Synthetic Oracle EBS/Oracle 19c descriptive-flexfield fixture packet.

This module is deliberately a local, deterministic fixture compiler.  It does
not connect to Oracle, Dataflow, BigQuery, or any other service.  Production
connectivity and execution remain separate adapters and milestone gates.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
from typing import Any

from cartridge_lab import CartridgePacket, canonical_digest


FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "oracle_ebs"
_ARTIFACT_NAMES = (
    "manifest",
    "metadata",
    "snapshot",
    "delta",
    "invalid",
    "bronze",
    "silver",
    "reconciliation",
)
_RECORD_KEYS = {
    "partyId",
    "application",
    "table",
    "context",
    "metadataVersion",
    "lastUpdateDate",
    "segments",
}
_METADATA_KEYS = {
    "application",
    "table",
    "context",
    "segment",
    "metadataVersion",
    "outputField",
    "dataType",
    "allowedValues",
}


class OracleEbsPacketError(ValueError):
    """The synthetic Oracle cartridge packet fails closed validation."""


def _fail(code: str) -> None:
    raise OracleEbsPacketError(code)


def _load_json(root: Path, name: str, expected: type[dict] | type[list]) -> Any:
    try:
        value = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OracleEbsPacketError(f"fixture_{name}_load") from exc
    if type(value) is not expected:
        _fail(f"fixture_{name}_shape")
    return value


def _text(value: object, code: str) -> str:
    if type(value) is not str or not value or any(ord(char) < 0x20 for char in value):
        _fail(code)
    return value


def _timestamp(value: object) -> dt.datetime:
    text = _text(value, "last_update_date")
    if not text.endswith("Z"):
        _fail("last_update_date")
    try:
        parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        _fail("last_update_date")
    if parsed.tzinfo != dt.timezone.utc:
        _fail("last_update_date")
    return parsed


def _metadata_index(rows: list[object]) -> dict[tuple[str, str, str, str, str], dict[str, object]]:
    index: dict[tuple[str, str, str, str, str], dict[str, object]] = {}
    if not rows:
        _fail("metadata_empty")
    for raw in rows:
        if type(raw) is not dict or set(raw) != _METADATA_KEYS:
            _fail("metadata_shape")
        row = raw
        key = tuple(
            _text(row[field], f"metadata_{field}")
            for field in ("application", "table", "context", "segment", "metadataVersion")
        )
        if key in index:
            _fail("context_ambiguous")
        if row["dataType"] != "string":
            _fail("metadata_data_type")
        allowed = row["allowedValues"]
        if type(allowed) is not list or not allowed or any(type(item) is not str for item in allowed):
            _fail("metadata_allowed_values")
        if len(set(allowed)) != len(allowed):
            _fail("metadata_allowed_values")
        _text(row["outputField"], "metadata_output_field")
        index[key] = row
    return index


def _validate_record_shape(
    raw: object, *, allow_empty_segments: bool = False
) -> dict[str, object]:
    if type(raw) is not dict or set(raw) != _RECORD_KEYS:
        _fail("record_shape")
    record = raw
    for field in ("partyId", "application", "table", "metadataVersion"):
        _text(record[field], f"record_{field}")
    if record["context"] is None:
        _fail("context_missing")
    _text(record["context"], "context_missing")
    _timestamp(record["lastUpdateDate"])
    segments = record["segments"]
    if type(segments) is not dict or (not segments and not allow_empty_segments):
        _fail("segments_shape")
    if any(type(key) is not str or type(value) is not str for key, value in segments.items()):
        _fail("segments_shape")
    return record


def _resolve_record(
    raw: object,
    metadata_rows: list[object],
) -> tuple[dict[str, object], dict[str, object]]:
    record = _validate_record_shape(raw)
    index = _metadata_index(metadata_rows)
    attributes: dict[str, str] = {}
    for segment, value in sorted(record["segments"].items()):
        key = (
            record["application"],
            record["table"],
            record["context"],
            segment,
            record["metadataVersion"],
        )
        definition = index.get(key)
        if definition is None:
            same_subject = any(candidate[:4] == key[:4] for candidate in index)
            _fail("metadata_version_mismatch" if same_subject else "segment_unmapped")
        if value not in definition["allowedValues"]:
            _fail("segment_value")
        output_field = definition["outputField"]
        if output_field in attributes:
            _fail("output_field_ambiguous")
        attributes[output_field] = value

    bronze = {
        "partyId": record["partyId"],
        "application": record["application"],
        "table": record["table"],
        "context": record["context"],
        "metadataVersion": record["metadataVersion"],
        "lastUpdateDate": record["lastUpdateDate"],
        "segments": {key: record["segments"][key] for key in sorted(record["segments"])},
    }
    silver = {
        "partyId": record["partyId"],
        "sourceKey": f"{record['application']}:{record['table']}:{record['partyId']}",
        "context": record["context"],
        "metadataVersion": record["metadataVersion"],
        "lastUpdateDate": record["lastUpdateDate"],
        "attributes": attributes,
    }
    return bronze, silver


def _record_key(record: dict[str, object]) -> tuple[str, str, str]:
    return record["application"], record["table"], record["partyId"]


def _compile_rows(
    snapshot: list[object],
    delta: list[object],
    metadata: list[object],
    watermark: dt.datetime,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int, int]:
    current: dict[tuple[str, str, str], dict[str, object]] = {}
    latest_timestamp: dict[tuple[str, str, str], dt.datetime] = {}
    for raw in snapshot:
        bronze, _ = _resolve_record(raw, metadata)
        key = _record_key(bronze)
        if key in current:
            _fail("snapshot_duplicate_key")
        current[key] = bronze
        latest_timestamp[key] = _timestamp(bronze["lastUpdateDate"])

    upserts = 0
    deletes = 0
    seen_delta: set[tuple[str, str, str, str]] = set()
    for raw in delta:
        if type(raw) is not dict or set(raw) != (_RECORD_KEYS | {"operation"}):
            _fail("delta_shape")
        operation = raw["operation"]
        record = {key: value for key, value in raw.items() if key != "operation"}
        _validate_record_shape(record, allow_empty_segments=operation == "delete")
        updated_at = _timestamp(record["lastUpdateDate"])
        if updated_at <= watermark:
            _fail("delta_not_after_watermark")
        record_key = _record_key(record)
        versioned_key = (*record_key, record["lastUpdateDate"])
        if versioned_key in seen_delta:
            _fail("delta_duplicate_key")
        seen_delta.add(versioned_key)
        if updated_at <= latest_timestamp.get(record_key, watermark):
            _fail("delta_not_after_current")
        if operation == "upsert":
            bronze, _ = _resolve_record(record, metadata)
            current[record_key] = bronze
            latest_timestamp[record_key] = updated_at
            upserts += 1
        elif operation == "delete":
            if record["segments"] != {}:
                _fail("delete_payload")
            existing = current.get(record_key)
            if existing is None:
                _fail("delete_missing_key")
            if any(existing[field] != record[field] for field in ("application", "table", "partyId", "context", "metadataVersion")):
                _fail("delete_identity_mismatch")
            current.pop(record_key)
            latest_timestamp[record_key] = updated_at
            deletes += 1
        else:
            _fail("delta_operation")

    bronze_rows = [current[key] for key in sorted(current)]
    silver_rows = [_resolve_record(row, metadata)[1] for row in bronze_rows]
    return bronze_rows, silver_rows, upserts, deletes


def _verify_invalid_cases(cases: list[object], metadata: list[object]) -> None:
    expected_ids = {"missing_context", "ambiguous_context", "metadata_version_mismatch"}
    seen: set[str] = set()
    for raw in cases:
        if type(raw) is not dict or set(raw) != {
            "caseId",
            "expectedCode",
            "duplicateMetadata",
            "record",
        }:
            _fail("invalid_case_shape")
        case_id = _text(raw["caseId"], "invalid_case_id")
        expected = _text(raw["expectedCode"], "invalid_expected_code")
        if case_id in seen:
            _fail("invalid_case_duplicate")
        seen.add(case_id)
        trial_metadata = copy.deepcopy(metadata)
        if raw["duplicateMetadata"] is True:
            trial_metadata.append(copy.deepcopy(trial_metadata[0]))
        elif raw["duplicateMetadata"] is not False:
            _fail("invalid_duplicate_metadata")
        try:
            _resolve_record(raw["record"], trial_metadata)
        except OracleEbsPacketError as exc:
            if str(exc) != expected:
                _fail("invalid_case_wrong_failure")
        else:
            _fail("invalid_case_accepted")
    if seen != expected_ids:
        _fail("invalid_case_coverage")


def build_oracle_ebs_packet(fixture_root: str | Path = FIXTURE_ROOT) -> CartridgePacket:
    """Build and fully verify the deterministic Oracle EBS fixture packet."""

    root = Path(fixture_root)
    manifest = _load_json(root, "manifest", dict)
    metadata = _load_json(root, "metadata", list)
    snapshot = _load_json(root, "snapshot", list)
    delta = _load_json(root, "delta", list)
    invalid = _load_json(root, "invalid", list)
    expected_bronze = _load_json(root, "bronze", list)
    expected_silver = _load_json(root, "silver", list)
    expected_reconciliation = _load_json(root, "reconciliation", dict)

    required_manifest = {
        "schemaVersion",
        "cartridgeId",
        "displayName",
        "sourceSystem",
        "readiness",
        "oracleDatabaseVersion",
        "metadataVersion",
        "watermark",
        "transformSpec",
    }
    if set(manifest) != required_manifest:
        _fail("manifest_shape")
    if (
        manifest["schemaVersion"] != "oracle-ebs-19c-fixture/v1"
        or manifest["cartridgeId"] != "oracle_ebs_19c"
        or manifest["sourceSystem"] != "oracle_ebs_19c"
        or manifest["readiness"] != "synthetic_fixture"
        or manifest["oracleDatabaseVersion"] != "19c"
    ):
        _fail("manifest_identity")
    metadata_version = _text(manifest["metadataVersion"], "manifest_metadata_version")
    if any(type(row) is not dict or row.get("metadataVersion") != metadata_version for row in metadata):
        _fail("manifest_metadata_version")
    _metadata_index(metadata)
    watermark = _timestamp(manifest["watermark"])
    metadata_digest = canonical_digest(metadata)
    transform_spec_digest = canonical_digest(
        {
            "metadataDigest": metadata_digest,
            "metadataVersion": metadata_version,
            "transformSpec": manifest["transformSpec"],
        }
    )

    _verify_invalid_cases(invalid, metadata)
    bronze, silver, upserts, deletes = _compile_rows(snapshot, delta, metadata, watermark)
    if bronze != expected_bronze:
        _fail("bronze_mismatch")
    if silver != expected_silver:
        _fail("silver_mismatch")

    reconciliation = {
        "snapshotRecords": len(snapshot),
        "deltaUpserts": upserts,
        "deltaDeletes": deletes,
        "finalRecords": len(silver),
        "deletedSourceKeys": [
            f"{row['application']}:{row['table']}:{row['partyId']}"
            for row in delta
            if row["operation"] == "delete"
        ],
        "inputDigest": canonical_digest({"snapshot": snapshot, "delta": delta}),
        "bronzeDigest": canonical_digest(bronze),
        "silverDigest": canonical_digest(silver),
        "metadataDigest": metadata_digest,
        "transformSpecDigest": transform_spec_digest,
        "lineageDigest": canonical_digest(
            {
                "input": canonical_digest({"snapshot": snapshot, "delta": delta}),
                "bronze": canonical_digest(bronze),
                "silver": canonical_digest(silver),
                "metadata": metadata_digest,
                "transform": transform_spec_digest,
            }
        ),
    }
    if reconciliation != expected_reconciliation:
        _fail("reconciliation_mismatch")

    return CartridgePacket(
        cartridge_id="oracle_ebs_19c",
        display_name=manifest["displayName"],
        source_system="oracle_ebs_19c",
        readiness="synthetic_fixture",
        transform_spec_digest=transform_spec_digest,
        artifacts={
            "manifest": manifest,
            "metadata": metadata,
            "snapshot": snapshot,
            "delta": delta,
            "invalid": invalid,
            "bronze": bronze,
            "silver": silver,
            "reconciliation": reconciliation,
        },
    )


__all__ = [
    "FIXTURE_ROOT",
    "OracleEbsPacketError",
    "build_oracle_ebs_packet",
]
