#!/usr/bin/env python3
"""Validate and render Keraun's non-secret, no-provisioning M6 cloud plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "cloud_architecture" / "m6_cloud_readiness.json"
_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_RESOURCE_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
_PROHIBITED_ROLE_SUFFIXES = {"roles/owner", "roles/editor", "roles/iam.serviceAccountTokenCreator"}
_SENSITIVE_KEYS = {"secret", "secretvalue", "password", "privatekey", "credential", "token"}


def _strict_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_json_pairs)


def _required_mapping(value: Any, name: str, issues: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        issues.append(f"{name} must be an object")
        return {}
    return value


def _required_list(value: Any, name: str, issues: list[str]) -> list[Any]:
    if not isinstance(value, list) or not value:
        issues.append(f"{name} must be a non-empty list")
        return []
    return value


def _reject_sensitive_keys(value: Any, path: str, issues: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if normalized in _SENSITIVE_KEYS:
                issues.append(f"{path}.{key} must not carry sensitive material")
            _reject_sensitive_keys(nested, f"{path}.{key}", issues)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, f"{path}[{index}]", issues)


def validate_manifest(document: dict[str, Any], project_root: Path = PROJECT_ROOT) -> list[str]:
    """Return deterministic validation failures; an empty list is valid."""
    issues: list[str] = []
    if document.get("schemaVersion") != "zeraun.m6.cloud-readiness/v1":
        issues.append("schemaVersion must be zeraun.m6.cloud-readiness/v1")
    if document.get("status") != "planned":
        issues.append("status must remain planned until independently evidenced")

    deployment = _required_mapping(document.get("deployment"), "deployment", issues)
    project_id = deployment.get("projectId")
    if not isinstance(project_id, str) or not _PROJECT_RE.fullmatch(project_id):
        issues.append("deployment.projectId is invalid")
    if deployment.get("region") != "us-central1":
        issues.append("deployment.region must be us-central1")
    baseline = _required_list(deployment.get("observedBaseline"), "deployment.observedBaseline", issues)
    if not all(isinstance(item, str) and item for item in baseline):
        issues.append("deployment.observedBaseline contains an invalid value")

    authority = _required_mapping(document.get("authority"), "authority", issues)
    if authority.get("lifecycle") != "cloud_sql_postgresql":
        issues.append("Cloud SQL PostgreSQL must remain lifecycle authority")
    if authority.get("analytics") != "bigquery_downstream_only":
        issues.append("BigQuery must remain downstream only")
    if authority.get("relay") != "pubsub_sanitized_outbox":
        issues.append("M6 relay must be the sanitized Pub/Sub outbox")
    if authority.get("approval") != "cloud_sql_authority_only":
        issues.append("approval authority must remain Cloud SQL only")
    reference = authority.get("lifecycleReference")
    expected_digest = authority.get("lifecycleReferenceSha256")
    if not isinstance(reference, str) or not isinstance(expected_digest, str) or not expected_digest.startswith("sha256:"):
        issues.append("authority lifecycle reference and SHA-256 are required")
    else:
        candidate = (project_root / reference).resolve()
        try:
            candidate.relative_to(project_root.resolve())
            actual_digest = "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual_digest != expected_digest:
                issues.append("authority lifecycle reference digest does not match repository file")
        except (OSError, ValueError):
            issues.append("authority lifecycle reference is unavailable or escapes repository")

    resources = _required_list(document.get("resources"), "resources", issues)
    resource_ids: set[str] = set()
    for index, raw_resource in enumerate(resources):
        resource = _required_mapping(raw_resource, f"resources[{index}]", issues)
        resource_id = resource.get("id")
        if not isinstance(resource_id, str) or not _RESOURCE_RE.fullmatch(resource_id) or resource_id in resource_ids:
            issues.append(f"resources[{index}].id must be a unique portable identifier")
        elif resource_id:
            resource_ids.add(resource_id)
        if resource.get("status") != "planned" or resource.get("ownerApprovalRequired") is not True:
            issues.append(f"resources[{index}] must remain planned and owner-approved")
        if not isinstance(resource.get("kind"), str) or not isinstance(resource.get("purpose"), str):
            issues.append(f"resources[{index}] requires kind and purpose")
        if not all(isinstance(api, str) and api.endswith(".googleapis.com") for api in _required_list(resource.get("requiredApis"), f"resources[{index}].requiredApis", issues)):
            issues.append(f"resources[{index}].requiredApis contains an invalid API name")

    identities = _required_list(document.get("identities"), "identities", issues)
    identity_ids: set[str] = set()
    for index, raw_identity in enumerate(identities):
        identity = _required_mapping(raw_identity, f"identities[{index}]", issues)
        identity_id = identity.get("id")
        if not isinstance(identity_id, str) or not _RESOURCE_RE.fullmatch(identity_id) or identity_id in identity_ids:
            issues.append(f"identities[{index}].id must be a unique portable identifier")
        elif identity_id:
            identity_ids.add(identity_id)
        bindings = _required_list(identity.get("bindings"), f"identities[{index}].bindings", issues)
        for binding_index, raw_binding in enumerate(bindings):
            binding = _required_mapping(raw_binding, f"identities[{index}].bindings[{binding_index}]", issues)
            role, resource = binding.get("role"), binding.get("resource")
            if role in _PROHIBITED_ROLE_SUFFIXES:
                issues.append(f"identities[{index}].bindings[{binding_index}] uses a prohibited broad role")
            if not isinstance(role, str) or not role.startswith("roles/"):
                issues.append(f"identities[{index}].bindings[{binding_index}].role is invalid")
            if resource not in resource_ids:
                issues.append(f"identities[{index}].bindings[{binding_index}] must target a declared resource")

    guardrails = _required_mapping(document.get("guardrails"), "guardrails", issues)
    prohibited_roles = _required_list(guardrails.get("prohibitedRoles"), "guardrails.prohibitedRoles", issues)
    if not _PROHIBITED_ROLE_SUFFIXES.issubset(set(prohibited_roles)):
        issues.append("guardrails must prohibit owner, editor, and token-creator roles")
    prohibited = set(_required_list(guardrails.get("prohibited"), "guardrails.prohibited", issues))
    required = set(_required_list(guardrails.get("required"), "guardrails.required", issues))
    for guardrail in {"service_account_keys", "project_wide_data_editor", "bigquery_lifecycle_reads", "raw_rows_in_outbox"}:
        if guardrail not in prohibited:
            issues.append(f"guardrails.prohibited must include {guardrail}")
    for guardrail in {"owner_approval_before_provisioning", "separate_migrator_and_runtime_identities", "outbox_delivery_cannot_mutate_lifecycle", "bigquery_is_not_an_authorization_source"}:
        if guardrail not in required:
            issues.append(f"guardrails.required must include {guardrail}")
    _required_list(_required_mapping(document.get("evidence"), "evidence", issues).get("requiredBeforeLiveClaim"), "evidence.requiredBeforeLiveClaim", issues)
    _reject_sensitive_keys(document, "manifest", issues)
    return sorted(set(issues))


def render_owner_change_plan(document: dict[str, Any]) -> str:
    """Render a stable, non-executable owner review checklist."""
    deployment = document["deployment"]
    lines = [
        "# Keraun M6 owner change plan",
        "",
        "Status: **planned, non-executable**. This document creates no Google Cloud resource.",
        "",
        f"Target: `{deployment['projectId']}` / `{deployment['region']}`.",
        "",
        "## Owner approval required before any provision or API enablement",
        "",
    ]
    for resource in document["resources"]:
        lines.append(f"- `{resource['id']}` — {resource['kind']}: {resource['purpose']}. APIs: {', '.join(resource['requiredApis'])}.")
    lines.extend(["", "## Resource-scoped identity bindings", ""])
    for identity in document["identities"]:
        bindings = ", ".join(f"{binding['role']} on {binding['resource']}" for binding in identity["bindings"])
        lines.append(f"- `{identity['id']}` ({identity['kind']}): {bindings}.")
    lines.extend(["", "## Live-claim evidence", ""])
    for item in document["evidence"]["requiredBeforeLiveClaim"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "No command in this plan enables APIs, creates a resource, changes IAM, connects to Cloud SQL, or writes BigQuery.", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the M6 no-provisioning cloud readiness manifest")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--render", action="store_true", help="print the deterministic owner-review plan after validation")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"M6 CLOUD READINESS INVALID: {error}", file=sys.stderr)
        return 2
    issues = validate_manifest(manifest)
    if issues:
        print("M6 CLOUD READINESS INVALID:", file=sys.stderr)
        print("\n".join(f"- {issue}" for issue in issues), file=sys.stderr)
        return 1
    print("M6 CLOUD READINESS VALID: planned only; no cloud resources were created.")
    if args.render:
        print()
        print(render_owner_change_plan(manifest), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
