from __future__ import annotations

import copy
import json
import shutil

import pytest

from cartridge_lab import REQUIRED_PACKET_ARTIFACTS, canonical_digest
from cartridge_lab.jde import (
    FIXTURE_DIRECTORY,
    JDEPacketError,
    apply_delta,
    build_bronze,
    build_reconciliation,
    build_silver,
    load_jde_packet,
)
from edge_runtime.adapters.jde import JDEDecodeError, decode_upmj


def test_packet_is_complete_synthetic_and_repeatably_digested() -> None:
    first = load_jde_packet()
    second = load_jde_packet()

    assert first.readiness == "synthetic_fixture"
    assert set(first.artifacts) == set(REQUIRED_PACKET_ARTIFACTS)
    assert first.digest == second.digest
    assert first.transform_spec_digest == second.transform_spec_digest
    assert first.reconciliation_digest == second.reconciliation_digest
    assert canonical_digest(first.artifacts) == canonical_digest(second.artifacts)

    # A second independent pair catches accidental process-local ordering.
    assert load_jde_packet().digest == load_jde_packet().digest


def test_summary_is_bounded_fixture_evidence() -> None:
    summary = load_jde_packet().ui_summary()

    assert summary["cartridgeId"] == "jde"
    assert summary["sourceSystem"] == "jd_edwards"
    assert summary["readiness"] == "synthetic_fixture"
    assert summary["snapshotRecords"] == 3
    assert summary["silverRecords"] == 3
    assert summary["invalidRecords"] == 7
    assert set(summary) == {
        "cartridgeId",
        "displayName",
        "sourceSystem",
        "readiness",
        "packetDigest",
        "transformSpecDigest",
        "reconciliationDigest",
        "snapshotRecords",
        "silverRecords",
        "invalidRecords",
    }


def test_delta_update_delete_insert_and_projection_reconcile() -> None:
    artifacts = load_jde_packet().artifacts
    final_rows = apply_delta(artifacts["snapshot"], artifacts["delta"])

    assert [(row["documentNumber"], row["lineNumber"]) for row in final_rows] == [
        (700001, 1),
        (700001, 2),
        (700003, 1),
    ]
    assert final_rows[0]["explanation"] == "Synthetic reviewed debit"
    assert build_bronze(artifacts["snapshot"], artifacts["delta"]) == artifacts["bronze"]
    assert build_silver(artifacts["snapshot"], artifacts["delta"]) == artifacts["silver"]
    assert build_reconciliation(
        artifacts["snapshot"],
        artifacts["delta"],
        artifacts["bronze"],
        artifacts["silver"],
    ) == artifacts["reconciliation"]
    assert artifacts["reconciliation"]["journalDigest"] == canonical_digest(artifacts["delta"])
    assert artifacts["reconciliation"]["status"] == "matched"


def test_silver_decodes_leap_day_and_removes_deleted_row() -> None:
    silver = load_jde_packet().artifacts["silver"]

    assert silver[0]["postingDate"] == "2024-02-29"
    assert silver[2]["postingDate"] == "2024-03-01"
    assert all(row["documentNumber"] != 700002 for row in silver)
    assert all("upmj" not in row for row in silver)


def test_invalid_journal_is_fail_closed_without_input_mutation() -> None:
    artifacts = load_jde_packet().artifacts
    snapshot = copy.deepcopy(artifacts["snapshot"])
    delta = copy.deepcopy(artifacts["delta"])
    original_snapshot = copy.deepcopy(snapshot)
    delta[-1]["sequence"] = 4
    attempted_delta = copy.deepcopy(delta)

    with pytest.raises(JDEPacketError, match="jde_delta_sequence"):
        apply_delta(snapshot, delta)

    assert snapshot == original_snapshot
    assert delta == attempted_delta


def test_invalid_fixture_vectors_are_all_rejected() -> None:
    invalid = load_jde_packet().artifacts["invalid"]
    for vector in invalid:
        with pytest.raises(JDEDecodeError):
            decode_upmj(vector["upmj"])


def test_manifest_detects_tampered_fixture(tmp_path) -> None:
    fixture_copy = tmp_path / "jde"
    shutil.copytree(FIXTURE_DIRECTORY, fixture_copy)
    snapshot_path = fixture_copy / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot[0]["amountMinor"] += 1
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(JDEPacketError):
        load_jde_packet(fixture_copy)


def test_journal_rejects_key_mismatch_and_missing_delete() -> None:
    artifacts = load_jde_packet().artifacts
    mismatched = copy.deepcopy(artifacts["delta"])
    mismatched[0]["row"]["lineNumber"] = 9
    with pytest.raises(JDEPacketError, match="jde_delta_key_mismatch"):
        apply_delta(artifacts["snapshot"], mismatched)

    missing_delete = [
        {
            "sequence": 1,
            "operation": "DELETE",
            "key": {
                "documentCompany": "00001",
                "documentType": "JE",
                "documentNumber": 999999,
                "lineNumber": 1,
                "ledgerType": "AA",
            },
            "row": None,
        }
    ]
    with pytest.raises(JDEPacketError, match="jde_delta_delete_missing"):
        apply_delta(artifacts["snapshot"], missing_delete)
