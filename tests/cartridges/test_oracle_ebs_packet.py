from __future__ import annotations

import json
import shutil

import pytest

from cartridge_lab import REQUIRED_PACKET_ARTIFACTS
from cartridge_lab.oracle_ebs import (
    FIXTURE_ROOT,
    OracleEbsPacketError,
    build_oracle_ebs_packet,
)


def _fixture_copy(tmp_path):
    target = tmp_path / "oracle_ebs"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def _mutate(root, artifact: str, mutate) -> None:
    path = root / f"{artifact}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_packet_is_complete_synthetic_and_double_digest_stable() -> None:
    first = build_oracle_ebs_packet()
    second = build_oracle_ebs_packet()

    assert first.readiness == "synthetic_fixture"
    assert set(first.artifacts) == set(REQUIRED_PACKET_ARTIFACTS)
    assert first.digest == second.digest
    assert first.reconciliation_digest == second.reconciliation_digest
    assert first.transform_spec_digest == second.transform_spec_digest
    assert first.artifacts["reconciliation"]["lineageDigest"].startswith("sha256:")
    assert "dataflow" not in json.dumps(first.ui_summary()).lower()
    assert "bigquery" not in json.dumps(first.ui_summary()).lower()


def test_context_keyed_flexfields_produce_expected_silver_rows() -> None:
    packet = build_oracle_ebs_packet()
    rows = {row["partyId"]: row for row in packet.artifacts["silver"]}

    assert rows["1001"]["attributes"] == {
        "customerTier": "PLATINUM",
        "regulatoryRegion": "NA",
    }
    assert rows["1004"]["attributes"] == {"paymentProfile": "NET45"}
    assert rows["1001"]["context"] == "CUSTOMER_EXT"
    assert rows["1004"]["context"] == "SUPPLIER_EXT"


def test_last_update_date_delta_and_delete_reconcile_exactly() -> None:
    packet = build_oracle_ebs_packet()
    reconciliation = packet.artifacts["reconciliation"]

    assert reconciliation["snapshotRecords"] == 3
    assert reconciliation["deltaUpserts"] == 2
    assert reconciliation["deltaDeletes"] == 1
    assert reconciliation["finalRecords"] == 3
    assert reconciliation["deletedSourceKeys"] == ["AR:HZ_PARTIES:1002"]
    assert {row["partyId"] for row in packet.artifacts["bronze"]} == {
        "1001",
        "1003",
        "1004",
    }


def test_fixture_proves_required_invalid_context_cases() -> None:
    packet = build_oracle_ebs_packet()
    failures = {case["caseId"]: case["expectedCode"] for case in packet.artifacts["invalid"]}
    assert failures == {
        "missing_context": "context_missing",
        "ambiguous_context": "context_ambiguous",
        "metadata_version_mismatch": "metadata_version_mismatch",
    }


def test_duplicate_metadata_key_fails_closed(tmp_path) -> None:
    root = _fixture_copy(tmp_path)
    _mutate(root, "metadata", lambda rows: rows.append(rows[0].copy()))

    with pytest.raises(OracleEbsPacketError, match="^context_ambiguous$"):
        build_oracle_ebs_packet(root)


def test_snapshot_metadata_version_mismatch_fails_closed(tmp_path) -> None:
    root = _fixture_copy(tmp_path)
    _mutate(root, "snapshot", lambda rows: rows[0].update(metadataVersion="FND_DFF_STALE"))

    with pytest.raises(OracleEbsPacketError, match="^metadata_version_mismatch$"):
        build_oracle_ebs_packet(root)


def test_metadata_content_tampering_changes_lineage_and_fails_closed(tmp_path) -> None:
    root = _fixture_copy(tmp_path)
    _mutate(root, "metadata", lambda rows: rows[0]["allowedValues"].append("DIAMOND"))

    with pytest.raises(OracleEbsPacketError, match="^reconciliation_mismatch$"):
        build_oracle_ebs_packet(root)


def test_missing_context_case_cannot_be_weakened(tmp_path) -> None:
    root = _fixture_copy(tmp_path)
    _mutate(root, "invalid", lambda rows: rows[0].update(expectedCode="segment_unmapped"))

    with pytest.raises(OracleEbsPacketError, match="^invalid_case_wrong_failure$"):
        build_oracle_ebs_packet(root)


def test_delta_at_watermark_is_not_incremental(tmp_path) -> None:
    root = _fixture_copy(tmp_path)
    _mutate(root, "delta", lambda rows: rows[0].update(lastUpdateDate="2026-08-01T00:00:00Z"))

    with pytest.raises(OracleEbsPacketError, match="^delta_not_after_watermark$"):
        build_oracle_ebs_packet(root)


def test_reverse_ordered_delta_for_one_key_fails_closed(tmp_path) -> None:
    root = _fixture_copy(tmp_path)

    def append_stale_event(rows):
        stale = rows[0].copy()
        stale["lastUpdateDate"] = "2026-08-02T07:00:00Z"
        rows.append(stale)

    _mutate(root, "delta", append_stale_event)
    with pytest.raises(OracleEbsPacketError, match="^delta_not_after_current$"):
        build_oracle_ebs_packet(root)


def test_delete_for_unknown_source_key_fails_closed(tmp_path) -> None:
    root = _fixture_copy(tmp_path)
    _mutate(root, "delta", lambda rows: rows[2].update(partyId="9999"))

    with pytest.raises(OracleEbsPacketError, match="^delete_missing_key$"):
        build_oracle_ebs_packet(root)


def test_delete_with_mismatched_context_fails_closed(tmp_path) -> None:
    root = _fixture_copy(tmp_path)
    _mutate(root, "delta", lambda rows: rows[2].update(context="CUSTOMER_EXT"))

    with pytest.raises(OracleEbsPacketError, match="^delete_identity_mismatch$"):
        build_oracle_ebs_packet(root)


def test_reconciliation_digest_tampering_is_rejected(tmp_path) -> None:
    root = _fixture_copy(tmp_path)
    _mutate(root, "reconciliation", lambda value: value.update(finalRecords=4))

    with pytest.raises(OracleEbsPacketError, match="^reconciliation_mismatch$"):
        build_oracle_ebs_packet(root)
