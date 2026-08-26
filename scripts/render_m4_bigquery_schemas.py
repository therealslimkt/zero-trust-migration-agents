#!/usr/bin/env python3
"""Render CREATE_NEVER-compatible BigQuery schemas from an approved snapshot.

This command is local-only. It never calls Google Cloud and never serializes
record batches or protected row values into its output schemas.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cloud_runtime.dataflow_template import bigquery_schema
from control_plane.canonical import (
    SOURCE_ORDER,
    TARGET_TABLES,
    canonical_json_bytes,
    document_digest,
    portfolio_plan_digest,
    require_digest,
    require_run_id,
)


_AUDIT_SCHEMA = Path(__file__).resolve().parents[1] / "dataflow" / "migration_audit.schema.json"


def _load_snapshot(path: Path, digest: str, dataset: str) -> tuple[str, dict[str, list[dict[str, str]]]]:
    try:
        stat_result = path.stat()
        if path.is_symlink() or stat_result.st_mode & 0o077:
            raise ValueError
        document = json.loads(path.read_bytes())
        require_run_id(document["runId"])
        require_digest(digest)
        require_digest(document["portfolioDigest"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("prepared snapshot is unavailable") from None
    if digest != document["portfolioDigest"]:
        raise ValueError("approved digest does not match prepared snapshot")
    sources = document.get("sources")
    if not isinstance(sources, list) or len(sources) != len(SOURCE_ORDER):
        raise ValueError("prepared snapshot is invalid")
    plans: list[dict[str, object]] = []
    rendered: dict[str, list[dict[str, str]]] = {}
    for source_id, source in zip(SOURCE_ORDER, sources):
        if type(source) is not dict or source.get("sourceId") != source_id:
            raise ValueError("prepared snapshot is invalid")
        plan = source.get("plan")
        if type(plan) is not dict:
            raise ValueError("prepared snapshot is invalid")
        if (
            plan.get("runId") != document["runId"]
            or plan.get("sourceId") != source_id
            or plan.get("target")
            != {"dataset": dataset, "table": TARGET_TABLES[source_id]}
            or document_digest(plan, omit=("planDigest",)) != plan.get("planDigest")
        ):
            raise ValueError("prepared snapshot is invalid")
        plans.append(plan)
        schema = bigquery_schema(plan.get("outputFields"))
        rendered[TARGET_TABLES[source_id]] = schema["fields"]  # type: ignore[assignment]
    if portfolio_plan_digest(plans) != document["portfolioDigest"]:
        raise ValueError("prepared snapshot is invalid")
    return str(document["runId"]), rendered


def _write_exclusive(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(canonical_json_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def render(snapshot: Path, digest: str, dataset: str, output_dir: Path) -> dict[str, object]:
    run_id, schemas = _load_snapshot(snapshot, digest, dataset)
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    outputs: list[str] = []
    for table, schema in schemas.items():
        path = output_dir / f"{table}.schema.json"
        _write_exclusive(path, schema)
        outputs.append(str(path))
    audit_path = output_dir / "migration_audit.schema.json"
    _write_exclusive(audit_path, json.loads(_AUDIT_SCHEMA.read_bytes()))
    outputs.append(str(audit_path))
    return {"runId": run_id, "dataset": dataset, "schemaFiles": outputs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Render approved BigQuery table schemas")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = render(args.snapshot, args.digest, args.dataset, args.output_dir)
    except Exception as exc:
        raise SystemExit(f"M4 schema rendering failed: {exc}") from None
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
