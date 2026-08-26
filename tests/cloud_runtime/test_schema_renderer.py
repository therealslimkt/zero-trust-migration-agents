from __future__ import annotations

import json
import os

import pytest

from control_plane.canonical import (
    SOURCE_ORDER,
    TARGET_TABLES,
    canonical_json_bytes,
    document_digest,
    portfolio_plan_digest,
)
from scripts.render_m4_bigquery_schemas import render


def _snapshot(tmp_path, *, field_name="customer_id"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    run_id = "mig_SCHEMARUNTIME01"
    sources = []
    for source_id in SOURCE_ORDER:
        plan = {
            "schemaVersion": "1.0.0",
            "planId": f"plan_{source_id.upper()}SCHEMARUNTIME",
            "runId": run_id,
            "sourceId": source_id,
            "sourceManifestDigest": "sha256:" + "1" * 64,
            "target": {
                "dataset": "legacy_migration",
                "table": TARGET_TABLES[source_id],
            },
            "operations": [{"operation": "rename", "from": "old", "to": field_name}],
            "outputFields": [
                {"name": field_name, "type": "string", "nullable": False}
            ],
        }
        plan["planDigest"] = document_digest(plan)
        sources.append({"sourceId": source_id, "plan": plan})
    digest = portfolio_plan_digest([source["plan"] for source in sources])
    path = tmp_path / "prepared.json"
    path.write_bytes(
        canonical_json_bytes(
            {
                "schemaVersion": "1.0.0",
                "runId": run_id,
                "portfolioDigest": digest,
                "model": "gemini-3.5-flash",
                "sources": sources,
            }
        )
    )
    os.chmod(path, 0o600)
    return path, digest


def test_renderer_writes_only_bound_target_and_audit_schemas(tmp_path):
    snapshot, digest = _snapshot(tmp_path)
    output_dir = tmp_path / "schemas"

    result = render(snapshot, digest, "legacy_migration", output_dir)

    assert result["runId"] == "mig_SCHEMARUNTIME01"
    assert len(result["schemaFiles"]) == 4
    for table in (*TARGET_TABLES.values(), "migration_audit"):
        path = output_dir / f"{table}.schema.json"
        fields = json.loads(path.read_bytes())
        assert fields
        assert "rows" not in path.read_text()
        assert path.stat().st_mode & 0o077 == 0
    target = json.loads((output_dir / "jde_f0101.schema.json").read_bytes())
    assert target[0] == {
        "mode": "REQUIRED",
        "name": "customer_id",
        "type": "STRING",
    }
    assert any(field["name"] == "_ztm_approval_digest" for field in target)
    assert any(field["name"] == "_ztm_policy_digest" for field in target)


def test_renderer_rejects_stale_digest_and_non_bigquery_field_names(tmp_path):
    snapshot, digest = _snapshot(tmp_path)
    with pytest.raises(ValueError, match="approved digest"):
        render(snapshot, "sha256:" + "f" * 64, "legacy_migration", tmp_path / "bad")

    dotted, dotted_digest = _snapshot(tmp_path / "nested", field_name="customer.id")
    with pytest.raises(Exception, match="template_schema"):
        render(dotted, dotted_digest, "legacy_migration", tmp_path / "dotted")
