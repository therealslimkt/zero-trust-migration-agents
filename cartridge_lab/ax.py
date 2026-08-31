"""Deterministic Microsoft Dynamics AX synthetic-fixture cartridge packet.

The shared :class:`CartridgePacket` owns the outer packet shape. This module
adds only AX-specific, local fixture validation: composite record identity,
table inheritance, ordered watermarks, tombstone application, and exact
reconciliation. It opens no connection and performs no cloud operation.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from cartridge_lab import CartridgePacket, CartridgePacketError, canonical_digest


AX_FIXTURE_ROOT: Final[Path] = Path(__file__).with_name("fixtures") / "ax"
AX_ARTIFACT_NAMES: Final[tuple[str, ...]] = (
    "manifest",
    "metadata",
    "snapshot",
    "delta",
    "invalid",
    "bronze",
    "silver",
    "reconciliation",
)
AX_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("company", "partition", "table", "recId")
AX_TRANSFORM_SPEC: Final[dict[str, object]] = {
    "kind": "synthetic_ax_transform",
    "version": 1,
    "identity": list(AX_IDENTITY_FIELDS),
    "watermark": ["modifiedDateTime", "recId"],
    "operations": ["snapshot", "upsert", "delete"],
    "inheritance": "derived_requires_same_scope_base",
}
AX_TRANSFORM_SPEC_DIGEST: Final[str] = canonical_digest(AX_TRANSFORM_SPEC)

_COMPANY = re.compile(r"^SYN[0-9]{2}$")
_PARTITION = re.compile(r"^synthetic_partition_[0-9]{2}$")
_TABLE = re.compile(r"^SyntheticAx[A-Za-z0-9]{3,48}$")
_TIMESTAMP = re.compile(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


class AXPacketError(CartridgePacketError):
    """An AX fixture violates a closed cartridge invariant."""


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class AXIdentity:
    """AX row identity; RecId alone is deliberately never sufficient."""

    company: str
    partition: str
    table: str
    rec_id: int

    @classmethod
    def from_value(cls, value: object) -> "AXIdentity":
        if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(AX_IDENTITY_FIELDS)):
            raise AXPacketError("ax_identity_shape")
        company = value["company"]
        partition = value["partition"]
        table = value["table"]
        rec_id = value["recId"]
        if type(company) is not str or _COMPANY.fullmatch(company) is None:
            raise AXPacketError("ax_identity_company")
        if type(partition) is not str or _PARTITION.fullmatch(partition) is None:
            raise AXPacketError("ax_identity_partition")
        if type(table) is not str or _TABLE.fullmatch(table) is None:
            raise AXPacketError("ax_identity_table")
        if type(rec_id) is not int or not (1 <= rec_id <= 2**63 - 1):
            raise AXPacketError("ax_identity_recid")
        return cls(company, partition, table, rec_id)

    def as_document(self) -> dict[str, object]:
        return {
            "company": self.company,
            "partition": self.partition,
            "table": self.table,
            "recId": self.rec_id,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class AXTable:
    name: str
    kind: str
    extends: str | None


def _exact_keys(value: object, keys: tuple[str, ...], code: str) -> Mapping[str, object]:
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(keys)):
        raise AXPacketError(code)
    return value


def _load_document(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AXPacketError("ax_fixture_load") from exc


def _metadata_tables(metadata: object) -> dict[str, AXTable]:
    document = _exact_keys(
        metadata,
        ("fixtureKind", "identityFields", "inheritance", "tables", "watermark"),
        "ax_metadata_shape",
    )
    if document["fixtureKind"] != "synthetic_ax_metadata_v1":
        raise AXPacketError("ax_metadata_fixture_kind")
    if document["identityFields"] != list(AX_IDENTITY_FIELDS):
        raise AXPacketError("ax_metadata_identity")
    inheritance = _exact_keys(
        document["inheritance"],
        ("baseLinkField", "scopeRule"),
        "ax_metadata_inheritance",
    )
    if inheritance != {
        "baseLinkField": "baseIdentity",
        "scopeRule": "same_company_partition_and_recid",
    }:
        raise AXPacketError("ax_metadata_inheritance")
    watermark = _exact_keys(
        document["watermark"],
        ("fields", "order", "semantics"),
        "ax_metadata_watermark",
    )
    if watermark != {
        "fields": ["modifiedDateTime", "recId"],
        "order": "ascending",
        "semantics": "strictly_after_last_committed",
    }:
        raise AXPacketError("ax_metadata_watermark")
    raw_tables = document["tables"]
    if type(raw_tables) is not list or not raw_tables:
        raise AXPacketError("ax_metadata_tables")
    tables: dict[str, AXTable] = {}
    for raw in raw_tables:
        table = _exact_keys(raw, ("extends", "kind", "table"), "ax_metadata_table_shape")
        name, kind, extends = table["table"], table["kind"], table["extends"]
        if type(name) is not str or _TABLE.fullmatch(name) is None or name in tables:
            raise AXPacketError("ax_metadata_table_name")
        if kind not in ("base", "derived"):
            raise AXPacketError("ax_metadata_table_kind")
        if kind == "base" and extends is not None:
            raise AXPacketError("ax_metadata_base_extends")
        if kind == "derived" and (type(extends) is not str or extends == name):
            raise AXPacketError("ax_metadata_derived_extends")
        tables[name] = AXTable(name, kind, extends)
    for table in tables.values():
        if table.kind == "derived":
            base = tables.get(table.extends or "")
            if base is None or base.kind != "base":
                raise AXPacketError("ax_metadata_orphan_table")
    return tables


def _record_identity(record: object, tables: Mapping[str, AXTable]) -> tuple[AXIdentity, Mapping[str, object]]:
    document = _exact_keys(
        record,
        ("baseIdentity", "identity", "modifiedDateTime", "values"),
        "ax_record_shape",
    )
    identity = AXIdentity.from_value(document["identity"])
    table = tables.get(identity.table)
    if table is None:
        raise AXPacketError("ax_record_unknown_table")
    modified = document["modifiedDateTime"]
    if type(modified) is not str or _TIMESTAMP.fullmatch(modified) is None:
        raise AXPacketError("ax_record_modified")
    if type(document["values"]) is not dict:
        raise AXPacketError("ax_record_values")
    base_value = document["baseIdentity"]
    if table.kind == "base":
        if base_value is not None:
            raise AXPacketError("ax_base_has_parent")
    else:
        base = AXIdentity.from_value(base_value)
        if (
            base.company != identity.company
            or base.partition != identity.partition
            or base.rec_id != identity.rec_id
        ):
            raise AXPacketError("ax_cross_scope_inheritance")
        if base.table != table.extends:
            raise AXPacketError("ax_wrong_base_table")
    return identity, document


def validate_ax_records(records: object, metadata: object) -> dict[AXIdentity, Mapping[str, object]]:
    """Validate one current-state row set and return its composite-key index."""

    tables = _metadata_tables(metadata)
    if type(records) is not list:
        raise AXPacketError("ax_records_shape")
    indexed: dict[AXIdentity, Mapping[str, object]] = {}
    for record in records:
        identity, document = _record_identity(record, tables)
        if identity in indexed:
            raise AXPacketError("ax_duplicate_identity")
        indexed[identity] = document
    for identity, record in indexed.items():
        table = tables[identity.table]
        if table.kind == "derived":
            base = AXIdentity.from_value(record["baseIdentity"])
            if base not in indexed:
                raise AXPacketError("ax_orphan_derived")
    return indexed


def _watermark(event: Mapping[str, object]) -> tuple[str, int]:
    value = _exact_keys(event["watermark"], ("modifiedDateTime", "recId"), "ax_delta_watermark")
    timestamp, rec_id = value["modifiedDateTime"], value["recId"]
    if type(timestamp) is not str or _TIMESTAMP.fullmatch(timestamp) is None:
        raise AXPacketError("ax_delta_watermark")
    if type(rec_id) is not int or rec_id < 1:
        raise AXPacketError("ax_delta_watermark")
    return timestamp, rec_id


def apply_ax_delta(snapshot: object, delta: object, metadata: object) -> list[dict[str, object]]:
    """Apply ordered upserts/tombstones and return deterministic current state."""

    current = dict(validate_ax_records(snapshot, metadata))
    tables = _metadata_tables(metadata)
    if type(delta) is not list:
        raise AXPacketError("ax_delta_shape")
    previous: tuple[str, int] | None = None
    for expected_sequence, raw in enumerate(delta, start=1):
        event = _exact_keys(
            raw,
            ("identity", "operation", "record", "sequence", "watermark"),
            "ax_delta_event_shape",
        )
        if event["sequence"] != expected_sequence:
            raise AXPacketError("ax_delta_sequence")
        watermark = _watermark(event)
        if previous is not None and watermark <= previous:
            raise AXPacketError("ax_delta_watermark_order")
        previous = watermark
        identity = AXIdentity.from_value(event["identity"])
        if watermark[1] != identity.rec_id:
            raise AXPacketError("ax_delta_watermark_identity")
        if identity.table not in tables:
            raise AXPacketError("ax_record_unknown_table")
        operation = event["operation"]
        if operation == "upsert":
            record_identity, record = _record_identity(event["record"], tables)
            if record_identity != identity:
                raise AXPacketError("ax_delta_identity_mismatch")
            if record["modifiedDateTime"] != watermark[0]:
                raise AXPacketError("ax_delta_watermark_record")
            current[identity] = record
        elif operation == "delete":
            if event["record"] is not None:
                raise AXPacketError("ax_delete_payload")
            if identity not in current:
                raise AXPacketError("ax_delete_missing")
            del current[identity]
        else:
            raise AXPacketError("ax_delta_operation")
    ordered = [dict(current[key]) for key in sorted(current)]
    validate_ax_records(ordered, metadata)
    return ordered


def build_ax_bronze(snapshot: object, delta: object, metadata: object) -> list[dict[str, object]]:
    """Build the append-only normalized evidence expected in bronze.json."""

    validate_ax_records(snapshot, metadata)
    if type(snapshot) is not list or type(delta) is not list:
        raise AXPacketError("ax_bronze_input")
    # Delta correctness is checked through the same merge used for silver.
    apply_ax_delta(snapshot, delta, metadata)
    bronze: list[dict[str, object]] = []
    for sequence, record in enumerate(snapshot, start=1):
        bronze.append(
            {
                "identity": record["identity"],
                "operation": "snapshot",
                "recordDigest": canonical_digest(record),
                "sequence": sequence,
            }
        )
    offset = len(bronze)
    for event in delta:
        bronze.append(
            {
                "identity": event["identity"],
                "operation": event["operation"],
                "recordDigest": canonical_digest(event["record"]) if event["record"] is not None else None,
                "sequence": offset + event["sequence"],
            }
        )
    return bronze


def _assert_invalid_cases(invalid: object, metadata: object) -> None:
    if type(invalid) is not list or len(invalid) != 3:
        raise AXPacketError("ax_invalid_fixture_shape")
    expected = {
        "orphan_derived": "ax_orphan_derived",
        "duplicate_identity": "ax_duplicate_identity",
        "cross_company_inheritance": "ax_cross_scope_inheritance",
    }
    seen: set[str] = set()
    for raw in invalid:
        case = _exact_keys(raw, ("case", "expectedCode", "records"), "ax_invalid_case_shape")
        name, code = case["case"], case["expectedCode"]
        if type(name) is not str or expected.get(name) != code or name in seen:
            raise AXPacketError("ax_invalid_case_contract")
        seen.add(name)
        try:
            validate_ax_records(case["records"], metadata)
        except AXPacketError as exc:
            if str(exc) != code:
                raise AXPacketError("ax_invalid_case_result") from exc
        else:
            raise AXPacketError("ax_invalid_case_accepted")
    if seen != set(expected):
        raise AXPacketError("ax_invalid_case_contract")


def validate_ax_artifacts(artifacts: Mapping[str, object]) -> None:
    """Validate the complete AX packet and its independently recomputed evidence."""

    if type(artifacts) is not dict or tuple(sorted(artifacts)) != tuple(sorted(AX_ARTIFACT_NAMES)):
        raise AXPacketError("ax_artifact_set")
    manifest = _exact_keys(
        artifacts["manifest"],
        (
            "artifactDigests",
            "cartridgeId",
            "fixtureId",
            "readiness",
            "snapshotHighWatermark",
            "transformSpecDigest",
        ),
        "ax_manifest_shape",
    )
    if manifest["cartridgeId"] != "dynamics_ax" or manifest["fixtureId"] != "synthetic_ax_packet_v1":
        raise AXPacketError("ax_manifest_identity")
    if manifest["readiness"] != "synthetic_fixture":
        raise AXPacketError("ax_manifest_readiness")
    if manifest["transformSpecDigest"] != AX_TRANSFORM_SPEC_DIGEST:
        raise AXPacketError("ax_transform_digest")
    high = _exact_keys(
        manifest["snapshotHighWatermark"],
        ("modifiedDateTime", "recId"),
        "ax_manifest_watermark",
    )
    if type(high["modifiedDateTime"]) is not str or _TIMESTAMP.fullmatch(high["modifiedDateTime"]) is None:
        raise AXPacketError("ax_manifest_watermark")
    if type(high["recId"]) is not int or high["recId"] < 1:
        raise AXPacketError("ax_manifest_watermark")
    embedded = manifest["artifactDigests"]
    digest_names = tuple(name for name in AX_ARTIFACT_NAMES if name != "manifest")
    if type(embedded) is not dict or tuple(sorted(embedded)) != tuple(sorted(digest_names)):
        raise AXPacketError("ax_manifest_digest_set")
    for name in digest_names:
        if embedded[name] != canonical_digest(artifacts[name]):
            raise AXPacketError("ax_artifact_digest_mismatch")

    snapshot = artifacts["snapshot"]
    delta = artifacts["delta"]
    metadata = artifacts["metadata"]
    snapshot_index = validate_ax_records(snapshot, metadata)
    if not snapshot_index:
        raise AXPacketError("ax_snapshot_empty")
    actual_high = max(
        (record["modifiedDateTime"], identity.rec_id)
        for identity, record in snapshot_index.items()
    )
    if actual_high != (high["modifiedDateTime"], high["recId"]):
        raise AXPacketError("ax_snapshot_watermark_mismatch")
    expected_silver = apply_ax_delta(snapshot, delta, metadata)
    if artifacts["silver"] != expected_silver:
        raise AXPacketError("ax_silver_mismatch")
    expected_bronze = build_ax_bronze(snapshot, delta, metadata)
    if artifacts["bronze"] != expected_bronze:
        raise AXPacketError("ax_bronze_mismatch")
    _assert_invalid_cases(artifacts["invalid"], metadata)

    if type(snapshot) is not list or type(delta) is not list:
        raise AXPacketError("ax_reconciliation_input")
    if delta and _watermark(delta[0]) <= (high["modifiedDateTime"], high["recId"]):
        raise AXPacketError("ax_delta_before_snapshot")
    inserts = sum(
        1
        for event in delta
        if event["operation"] == "upsert"
        and AXIdentity.from_value(event["identity"])
        not in snapshot_index
    )
    deletes = sum(1 for event in delta if event["operation"] == "delete")
    updates = sum(1 for event in delta if event["operation"] == "upsert") - inserts
    expected_counts = {
        "bronzeRows": len(expected_bronze),
        "deleteTombstones": deletes,
        "deltaRows": len(delta),
        "insertedIdentities": inserts,
        "matchedIdentityUpdates": updates,
        "silverRows": len(expected_silver),
        "snapshotRows": len(snapshot),
        "unmatchedDeletes": 0,
    }
    reconciliation = _exact_keys(
        artifacts["reconciliation"],
        ("counts", "countsDigest", "finalIdentityDigest", "status"),
        "ax_reconciliation_shape",
    )
    if reconciliation["status"] != "reconciled" or reconciliation["counts"] != expected_counts:
        raise AXPacketError("ax_reconciliation_counts")
    if reconciliation["countsDigest"] != canonical_digest(expected_counts):
        raise AXPacketError("ax_reconciliation_counts_digest")
    final_identities = [identity.as_document() for identity in sorted(validate_ax_records(expected_silver, metadata))]
    if reconciliation["finalIdentityDigest"] != canonical_digest(final_identities):
        raise AXPacketError("ax_reconciliation_identity_digest")


def load_ax_packet(root: str | Path = AX_FIXTURE_ROOT) -> CartridgePacket:
    """Load and validate the complete local AX fixture packet."""

    fixture_root = Path(root)
    artifacts = {name: _load_document(fixture_root / f"{name}.json") for name in AX_ARTIFACT_NAMES}
    validate_ax_artifacts(artifacts)
    return CartridgePacket(
        cartridge_id="dynamics_ax",
        display_name="Microsoft Dynamics AX",
        source_system="microsoft_dynamics_ax",
        readiness="synthetic_fixture",
        transform_spec_digest=AX_TRANSFORM_SPEC_DIGEST,
        artifacts=artifacts,
    )


__all__ = [
    "AX_ARTIFACT_NAMES",
    "AX_FIXTURE_ROOT",
    "AX_IDENTITY_FIELDS",
    "AX_TRANSFORM_SPEC_DIGEST",
    "AXIdentity",
    "AXPacketError",
    "apply_ax_delta",
    "build_ax_bronze",
    "load_ax_packet",
    "validate_ax_artifacts",
    "validate_ax_records",
]
