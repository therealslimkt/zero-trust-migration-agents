from __future__ import annotations

import argparse
import json
import os

import pytest

from control_plane.canonical import TARGET_TABLES, canonical_json_bytes, document_digest
from scripts.verify_m3_control_plane import _execute, _load_prepared, _write_exclusive


RUN_ID = "mig_CANARYTEST001"
DIGESTS = {
    "jde": "sha256:" + "1" * 64,
    "dynamics": "sha256:" + "2" * 64,
    "ebs": "sha256:" + "3" * 64,
}


def _prepared_document():
    sources = []
    for source_id in ("jde", "dynamics", "ebs"):
        manifest = {
            "schemaVersion": "1.0.0",
            "manifestId": "manifest_" + source_id.upper() + "000000000000",
            "runId": RUN_ID,
            "sourceId": source_id,
            "hostname": {
                "jde": "legacy-jde-db",
                "dynamics": "dynamics-ax",
                "ebs": "oracle-ebs-19c",
            }[source_id],
            "inventoryDigest": "sha256:" + "4" * 64,
            "recordSets": [
                {
                    "name": "RECORDS",
                    "recordCount": 1,
                    "byteCount": 10,
                    "schemaDigest": "sha256:" + "5" * 64,
                }
            ],
            "observedAt": "2026-08-26T22:00:00Z",
        }
        manifest_digest = document_digest(manifest)
        report = {
            "schemaVersion": "1.0.0",
            "reportId": "report_" + source_id.upper() + "000000000000",
            "runId": RUN_ID,
            "sourceId": source_id,
            "sourceManifestDigest": manifest_digest,
            "deterministicCheck": {},
            "localGemmaCheck": {},
            "unresolvedFindingCount": 0,
            "status": "passed",
            "failClosed": True,
            "completedAt": "2026-08-26T22:00:00Z",
        }
        report["reportDigest"] = document_digest(report, omit=("reportDigest",))
        batch = {
            "schemaVersion": "1.0.0",
            "batchId": "batch_" + source_id.upper() + "00000000000000",
            "runId": RUN_ID,
            "sourceId": source_id,
            "sourceManifestDigest": manifest_digest,
            "recordSet": "RECORDS",
            "schemaDigest": "sha256:" + "5" * 64,
            "recordCount": 1,
            "records": [
                {
                    "recordId": "rec_" + source_id.upper() + "00000001",
                    "ordinal": 0,
                    "values": [
                        {
                            "field": "customer_token",
                            "protection": "tokenized",
                            "value": "tok_PROTECTED_SENTINEL",
                        }
                    ],
                }
            ],
        }
        plan = {
            "schemaVersion": "1.0.0",
            "planId": "plan_" + source_id.upper() + "00000000000000",
            "runId": RUN_ID,
            "sourceId": source_id,
            "sourceManifestDigest": manifest_digest,
            "target": {
                "dataset": "legacy_migration",
                "table": TARGET_TABLES[source_id],
            },
            "operations": [
                {
                    "operation": "rename",
                    "from": "customer_token",
                    "to": "customer_id",
                }
            ],
            "outputFields": [
                {"name": "customer_id", "type": "string", "nullable": False}
            ],
            "planDigest": DIGESTS[source_id],
        }
        # The test replaces the placeholder digests below with real anchors.
        plan["planDigest"] = document_digest(plan, omit=("planDigest",))
        sources.append(
            {
                "sourceId": source_id,
                "sourceManifest": manifest,
                "recordBatch": batch,
                "redactionReport": report,
                "plan": plan,
            }
        )
    from control_plane.canonical import portfolio_plan_digest

    digest = portfolio_plan_digest([source["plan"] for source in sources])
    return {
        "schemaVersion": "1.0.0",
        "runId": RUN_ID,
        "portfolioDigest": digest,
        "model": "gemini-test",
        "sources": sources,
    }


def test_snapshot_is_owner_only_and_cannot_be_overwritten(tmp_path):
    path = tmp_path / "prepared.json"
    _write_exclusive(path, canonical_json_bytes(_prepared_document()))
    assert os.stat(path).st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        _write_exclusive(path, b"replacement")


def test_execute_requires_exact_digest_and_emits_only_reconciliation(tmp_path):
    path = tmp_path / "prepared.json"
    document = _prepared_document()
    _write_exclusive(path, canonical_json_bytes(document))
    args = argparse.Namespace(
        snapshot=path,
        digest=document["portfolioDigest"],
        approver="human-reviewer",
    )

    result = _execute(args)

    assert result["status"] == "passed"
    assert result["sourceCount"] == 3
    assert [source["sourceId"] for source in result["sources"]] == [
        "jde",
        "dynamics",
        "ebs",
    ]
    assert "tok_PROTECTED_SENTINEL" not in json.dumps(result)
    args.digest = "sha256:" + "9" * 64
    with pytest.raises(ValueError, match="approval digest"):
        _execute(args)


def test_snapshot_loader_rejects_permissive_or_corrupt_files(tmp_path):
    path = tmp_path / "prepared.json"
    path.write_text("{bad", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="snapshot is unavailable"):
        _load_prepared(path)

    path.write_bytes(canonical_json_bytes(_prepared_document()))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="snapshot is unavailable"):
        _load_prepared(path)
