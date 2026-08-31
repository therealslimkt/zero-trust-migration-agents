from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

from scripts.validate_m6_cloud_readiness import (
    DEFAULT_MANIFEST,
    PROJECT_ROOT,
    load_manifest,
    render_owner_change_plan,
    validate_manifest,
)


def test_checked_in_m6_manifest_is_planned_and_valid() -> None:
    assert validate_manifest(load_manifest()) == []


def test_validator_rejects_live_claim_broad_iam_and_authority_drift() -> None:
    manifest = copy.deepcopy(load_manifest())
    manifest["status"] = "deployed"
    manifest["identities"][0]["bindings"][0]["role"] = "roles/editor"
    manifest["authority"]["analytics"] = "bigquery_authority"

    issues = validate_manifest(manifest)

    assert "status must remain planned until independently evidenced" in issues
    assert "BigQuery must remain downstream only" in issues
    assert any("prohibited broad role" in issue for issue in issues)


def test_validator_rejects_undeclared_resource_and_sensitive_material() -> None:
    manifest = copy.deepcopy(load_manifest())
    manifest["identities"][0]["bindings"][0]["resource"] = "undeclared-resource"
    manifest["deployment"]["token"] = "must-not-be-here"

    issues = validate_manifest(manifest)

    assert any("must target a declared resource" in issue for issue in issues)
    assert "manifest.deployment.token must not carry sensitive material" in issues


def test_validator_binds_exact_m3_migration_bytes() -> None:
    manifest = copy.deepcopy(load_manifest())
    manifest["authority"]["lifecycleReferenceSha256"] = "sha256:" + "0" * 64

    assert "authority lifecycle reference digest does not match repository file" in validate_manifest(manifest)


def test_owner_change_plan_is_deterministic_and_non_executable() -> None:
    manifest = load_manifest()
    rendered = render_owner_change_plan(manifest)

    assert rendered == render_owner_change_plan(manifest)
    assert "planned, non-executable" in rendered
    assert "gcloud " not in rendered
    assert "cloud-sql-authority" in rendered
    assert "bigquery_is_not_an_authorization_source" not in rendered


def test_cli_validates_checked_in_manifest_and_renders_owner_plan() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_m6_cloud_readiness.py", "--render"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "M6 CLOUD READINESS VALID" in result.stdout
    assert "# Keraun M6 owner change plan" in result.stdout
    assert str(DEFAULT_MANIFEST) not in result.stdout
