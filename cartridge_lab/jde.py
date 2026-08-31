"""Deterministic JD Edwards synthetic-fixture cartridge helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from cartridge_lab import CartridgePacket, CartridgePacketError, canonical_digest
from edge_runtime.adapters.jde import JDEDecodeError, decode_upmj


FIXTURE_DIRECTORY = Path(__file__).with_name("fixtures") / "jde"
_ARTIFACT_FILES = {
    "manifest": "manifest.json",
    "metadata": "metadata.json",
    "snapshot": "snapshot.json",
    "delta": "delta.json",
    "invalid": "invalid.json",
    "bronze": "bronze.json",
    "silver": "silver.json",
    "reconciliation": "reconciliation.json",
}
_KEY_FIELDS = (
    "documentCompany",
    "documentType",
    "documentNumber",
    "lineNumber",
    "ledgerType",
)
_ROW_FIELDS = _KEY_FIELDS + (
    "upmj",
    "account",
    "amountMinor",
    "currency",
    "explanation",
)
_DELTA_FIELDS = ("sequence", "operation", "key", "row")
_OPERATIONS = frozenset({"INSERT", "UPDATE", "DELETE"})


class JDEPacketError(CartridgePacketError):
    """A JDE fixture violates its closed, local-only packet contract."""


def _fail(code: str) -> None:
    raise JDEPacketError(code)


def _exact_dict(value: object, fields: Sequence[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(fields):
        _fail(code)
    return value


def _bounded_text(value: object, code: str, *, maximum: int = 80) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(character) < 0x20 for character in value)
    ):
        _fail(code)
    return value


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(code)
    return value


def _validate_key(value: object) -> dict[str, Any]:
    key = _exact_dict(value, _KEY_FIELDS, "jde_key_shape")
    _bounded_text(key["documentCompany"], "jde_key_company", maximum=12)
    _bounded_text(key["documentType"], "jde_key_document_type", maximum=2)
    _positive_int(key["documentNumber"], "jde_key_document_number")
    _positive_int(key["lineNumber"], "jde_key_line_number")
    _bounded_text(key["ledgerType"], "jde_key_ledger_type", maximum=2)
    return key


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, int, int, str]:
    return tuple(row[field] for field in _KEY_FIELDS)  # type: ignore[return-value]


def _validate_row(value: object) -> dict[str, Any]:
    row = _exact_dict(value, _ROW_FIELDS, "jde_row_shape")
    _validate_key({field: row[field] for field in _KEY_FIELDS})
    if type(row["upmj"]) is not int:
        _fail("jde_row_upmj")
    try:
        decode_upmj(row["upmj"])
    except JDEDecodeError:
        _fail("jde_row_upmj")
    _bounded_text(row["account"], "jde_row_account", maximum=64)
    if type(row["amountMinor"]) is not int:
        _fail("jde_row_amount")
    currency = _bounded_text(row["currency"], "jde_row_currency", maximum=3)
    if len(currency) != 3 or currency.upper() != currency:
        _fail("jde_row_currency")
    _bounded_text(row["explanation"], "jde_row_explanation", maximum=120)
    return row


def _copy_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field: row[field] for field in _ROW_FIELDS}


def apply_delta(snapshot: object, delta: object) -> tuple[dict[str, Any], ...]:
    """Apply an ordered journal atomically and return key-sorted current rows.

    Validation occurs against a private copy. Callers' snapshot and delta values
    are never mutated, including when a later journal entry is rejected.
    """

    if type(snapshot) is not list or type(delta) is not list:
        _fail("jde_journal_collection")

    current: dict[tuple[str, str, int, int, str], dict[str, Any]] = {}
    for raw_row in snapshot:
        row = _validate_row(raw_row)
        key = _row_key(row)
        if key in current:
            _fail("jde_snapshot_duplicate")
        current[key] = _copy_row(row)

    for expected_sequence, raw_entry in enumerate(delta, start=1):
        entry = _exact_dict(raw_entry, _DELTA_FIELDS, "jde_delta_shape")
        if type(entry["sequence"]) is not int or entry["sequence"] != expected_sequence:
            _fail("jde_delta_sequence")
        operation = entry["operation"]
        if type(operation) is not str or operation not in _OPERATIONS:
            _fail("jde_delta_operation")
        key = _validate_key(entry["key"])
        key_tuple = _row_key(key)

        if operation == "DELETE":
            if entry["row"] is not None:
                _fail("jde_delta_delete_row")
            if key_tuple not in current:
                _fail("jde_delta_delete_missing")
            del current[key_tuple]
            continue

        row = _validate_row(entry["row"])
        if _row_key(row) != key_tuple:
            _fail("jde_delta_key_mismatch")
        if operation == "INSERT":
            if key_tuple in current:
                _fail("jde_delta_insert_existing")
        elif key_tuple not in current:
            _fail("jde_delta_update_missing")
        current[key_tuple] = _copy_row(row)

    return tuple(current[key] for key in sorted(current))


def build_bronze(snapshot: object, delta: object) -> list[dict[str, Any]]:
    """Create the deterministic append-only local journal projection."""

    # Full validation also proves the ordered journal can be applied atomically.
    apply_delta(snapshot, delta)
    assert isinstance(snapshot, list) and isinstance(delta, list)
    bronze: list[dict[str, Any]] = []
    for row in snapshot:
        bronze.append({"sequence": 0, "operation": "SNAPSHOT", "row": _copy_row(row)})
    for entry in delta:
        bronze.append(
            {
                "sequence": entry["sequence"],
                "operation": entry["operation"],
                "key": dict(entry["key"]),
                "row": None if entry["row"] is None else _copy_row(entry["row"]),
            }
        )
    return bronze


def build_silver(snapshot: object, delta: object) -> list[dict[str, Any]]:
    """Create current rows with the UPMJ field decoded to an ISO date."""

    silver: list[dict[str, Any]] = []
    for row in apply_delta(snapshot, delta):
        posting_date = decode_upmj(row["upmj"])
        projected = _copy_row(row)
        del projected["upmj"]
        projected["postingDate"] = posting_date.isoformat() if posting_date else None
        silver.append(projected)
    return silver


def build_reconciliation(
    snapshot: object,
    delta: object,
    bronze: object,
    silver: object,
) -> dict[str, Any]:
    """Return counts and immutable digests proving local journal agreement."""

    final_rows = apply_delta(snapshot, delta)
    expected_bronze = build_bronze(snapshot, delta)
    expected_silver = build_silver(snapshot, delta)
    if bronze != expected_bronze or silver != expected_silver:
        _fail("jde_projection_mismatch")
    assert isinstance(snapshot, list) and isinstance(delta, list)
    operations = [entry["operation"] for entry in delta]
    deleted_keys = [
        dict(entry["key"]) for entry in delta if entry["operation"] == "DELETE"
    ]
    return {
        "schemaVersion": 1,
        "status": "matched",
        "snapshotCount": len(snapshot),
        "deltaCount": len(delta),
        "insertCount": operations.count("INSERT"),
        "updateCount": operations.count("UPDATE"),
        "deleteCount": operations.count("DELETE"),
        "finalCount": len(final_rows),
        "deletedKeys": deleted_keys,
        "snapshotDigest": canonical_digest(snapshot),
        "journalDigest": canonical_digest(delta),
        "bronzeDigest": canonical_digest(bronze),
        "silverDigest": canonical_digest(silver),
    }


def _validate_metadata(value: object) -> dict[str, Any]:
    fields = (
        "schemaVersion",
        "fixtureId",
        "sourceSystem",
        "sourceTable",
        "readiness",
        "synthetic",
        "transformSpec",
    )
    metadata = _exact_dict(value, fields, "jde_metadata_shape")
    if metadata["schemaVersion"] != 1:
        _fail("jde_metadata_version")
    if metadata["fixtureId"] != "jde_f0911_hero_v1":
        _fail("jde_metadata_fixture")
    if metadata["sourceSystem"] != "jd_edwards" or metadata["sourceTable"] != "F0911":
        _fail("jde_metadata_source")
    if metadata["readiness"] != "synthetic_fixture" or metadata["synthetic"] is not True:
        _fail("jde_metadata_readiness")
    transform = _exact_dict(
        metadata["transformSpec"],
        ("dateEncoding", "keyFields", "amountUnit", "deltaOrder", "deleteMode"),
        "jde_transform_shape",
    )
    if transform != {
        "dateEncoding": "UPMJ_CYYDDD",
        "keyFields": list(_KEY_FIELDS),
        "amountUnit": "minor_currency_unit",
        "deltaOrder": "strict_contiguous_sequence",
        "deleteMode": "hard_delete",
    }:
        _fail("jde_transform_value")
    return metadata


def _validate_invalid_vectors(value: object) -> None:
    if type(value) is not list or not value:
        _fail("jde_invalid_shape")
    for vector in value:
        item = _exact_dict(vector, ("case", "upmj", "expectedError"), "jde_invalid_vector")
        _bounded_text(item["case"], "jde_invalid_case", maximum=40)
        if item["expectedError"] != "JDE_UPMJ_INVALID":
            _fail("jde_invalid_expectation")
        try:
            decode_upmj(item["upmj"])
        except JDEDecodeError:
            continue
        _fail("jde_invalid_accepted")


def _read_artifacts(directory: Path) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    for name, filename in _ARTIFACT_FILES.items():
        try:
            artifacts[name] = json.loads((directory / filename).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JDEPacketError(f"jde_artifact_load_{name}") from exc
    return artifacts


def load_jde_packet(directory: str | Path = FIXTURE_DIRECTORY) -> CartridgePacket:
    """Load and fully validate the bounded synthetic JDE hero packet."""

    artifacts = _read_artifacts(Path(directory))
    metadata = _validate_metadata(artifacts["metadata"])
    _validate_invalid_vectors(artifacts["invalid"])

    expected_bronze = build_bronze(artifacts["snapshot"], artifacts["delta"])
    expected_silver = build_silver(artifacts["snapshot"], artifacts["delta"])
    if artifacts["bronze"] != expected_bronze or artifacts["silver"] != expected_silver:
        _fail("jde_projection_mismatch")
    expected_reconciliation = build_reconciliation(
        artifacts["snapshot"],
        artifacts["delta"],
        artifacts["bronze"],
        artifacts["silver"],
    )
    if artifacts["reconciliation"] != expected_reconciliation:
        _fail("jde_reconciliation_mismatch")

    manifest = _exact_dict(
        artifacts["manifest"],
        ("schemaVersion", "fixtureId", "artifactFiles", "artifactDigests"),
        "jde_manifest_shape",
    )
    if manifest["schemaVersion"] != 1 or manifest["fixtureId"] != metadata["fixtureId"]:
        _fail("jde_manifest_identity")
    expected_files = {
        name: filename
        for name, filename in _ARTIFACT_FILES.items()
        if name != "manifest"
    }
    if manifest["artifactFiles"] != expected_files:
        _fail("jde_manifest_files")
    expected_digests = {
        name: canonical_digest(artifacts[name]) for name in _ARTIFACT_FILES if name != "manifest"
    }
    if manifest["artifactDigests"] != expected_digests:
        _fail("jde_manifest_digest")

    return CartridgePacket(
        cartridge_id="jde",
        display_name="JD Edwards EnterpriseOne",
        source_system="jd_edwards",
        readiness="synthetic_fixture",
        transform_spec_digest=canonical_digest(metadata["transformSpec"]),
        artifacts=artifacts,
    )
