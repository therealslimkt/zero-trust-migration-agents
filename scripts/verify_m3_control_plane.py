#!/usr/bin/env python3
"""Run the live M3 boundary without printing protected record values.

The first command creates a 0600 prepared snapshot and stops at the human
approval boundary. The second command requires the exact displayed digest,
revalidates the complete snapshot, and runs the closed in-memory interpreter.
Neither command writes to BigQuery or launches Dataflow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from control_plane.artifacts import EdgeArtifacts, build_edge_artifacts
from control_plane.canonical import SOURCE_ORDER, canonical_json_bytes
from control_plane.gemini_planner import (
    GeminiPlanCompiler,
    antigravity_model_call_factory,
)
from control_plane.workflow import PreparedPortfolio, execute_portfolio, prepare_portfolio
from edge_runtime.adapters import btrieve, jde, maxdb
from edge_runtime.transport import TailscaleSSHTransport
from edge_runtime.types import SOURCE_SPECS
from edge_security.local_gemma_agent import TailscaleGemmaReviewer
from edge_security.pii_redactor import DeterministicRedactor
from ztm_security.approval import ApprovalRecord


DECODERS = {
    "jde": jde.decode,
    "maxdb": maxdb.decode,
    "btrieve": btrieve.decode,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _new_run_id() -> str:
    return "mig_" + uuid.uuid4().hex[:20]


def _write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _load_prepared(path: Path) -> PreparedPortfolio:
    try:
        if path.stat().st_mode & 0o077:
            raise ValueError
        document = json.loads(path.read_bytes())
        encoded = canonical_json_bytes(document)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("prepared snapshot is unavailable") from None
    return PreparedPortfolio(encoded)


def _collect_edge(
    *, run_id: str, observed_at: str, tailscale_binary: str
) -> tuple[dict[str, EdgeArtifacts], list[dict[str, object]]]:
    transport = TailscaleSSHTransport(tailscale_binary=tailscale_binary)
    reviewer = TailscaleGemmaReviewer(tailscale_binary=tailscale_binary)
    redactor = DeterministicRedactor(secrets.token_bytes(32))
    artifacts: dict[str, EdgeArtifacts] = {}
    summaries: list[dict[str, object]] = []

    for source_id in SOURCE_ORDER:
        payload = transport.read(SOURCE_SPECS[source_id])
        decoded = DECODERS[source_id](payload)
        deterministic = redactor.sanitize(decoded)
        review = reviewer.review(deterministic.sanitized)
        built = build_edge_artifacts(
            run_id=run_id,
            observed_at=observed_at,
            payload=payload,
            decoded=decoded,
            deterministic=deterministic,
            gemma_review=review,
        )
        artifacts[source_id] = built
        summaries.append(
            {
                "sourceId": source_id,
                "hostname": payload.spec.hostname,
                "byteCount": payload.size_bytes,
                "sourceDigest": "sha256:" + payload.sha256,
                "recordCount": len(decoded.records),
                "protectedFindingCount": deterministic.finding_count,
                "unresolvedFindingCount": review.finding_count,
                "localGemmaModel": review.model,
                "sourceManifestDigest": built.record_batch[
                    "sourceManifestDigest"
                ],
                "recordBatchId": built.record_batch["batchId"],
                "redactionReportDigest": built.redaction_report["reportDigest"],
            }
        )
    return artifacts, summaries


async def _plan(args: argparse.Namespace) -> dict[str, object]:
    run_id = _new_run_id()
    observed_at = _now()
    artifacts, summaries = _collect_edge(
        run_id=run_id,
        observed_at=observed_at,
        tailscale_binary=args.tailscale_binary,
    )
    compiler = GeminiPlanCompiler(
        antigravity_model_call_factory(
            model_name=args.model,
            location=args.location,
            project=args.project,
        ),
        args.model,
        dataset=args.dataset,
    )
    prepared = await prepare_portfolio(
        artifacts_by_source=artifacts,
        compiler=compiler,
    )
    _write_exclusive(args.snapshot, canonical_json_bytes(prepared.as_document()))
    return {
        "status": "awaiting_approval",
        "runId": prepared.run_id,
        "portfolioPlanDigest": prepared.portfolio_digest,
        "model": prepared.model,
        "snapshot": str(args.snapshot),
        "sources": summaries,
    }


def _execute(args: argparse.Namespace) -> dict[str, object]:
    prepared = _load_prepared(args.snapshot)
    if args.digest != prepared.portfolio_digest:
        raise ValueError("approval digest does not match prepared snapshot")
    approval = ApprovalRecord(
        approver=args.approver,
        plan_digest=args.digest,
        timestamp=_now(),
        portfolio_run_id=prepared.run_id,
    )
    # The edge artifact/report validators have proved no non-overridable
    # category is present. Passing the empty finding set is explicit and
    # mandatory; omission is rejected by the execution API.
    result = execute_portfolio(
        prepared=prepared,
        approval=approval,
        policy_categories=frozenset(),
    )
    return {
        "status": "passed",
        "runId": result.run_id,
        "portfolioPlanDigest": result.portfolio_digest,
        "approvedBy": approval.approver,
        "approvedAt": approval.timestamp,
        "sourceCount": len(result.reconciliations),
        "sources": [
            {
                "sourceId": item.source_id,
                "target": dict(item.target),
                "recordCount": item.row_count,
                "outputDigest": item.output_digest,
            }
            for item in result.reconciliations
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify live three-source planning and digest-bound execution"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="stop at the human approval boundary")
    plan.add_argument("--snapshot", type=Path, required=True)
    plan.add_argument("--tailscale-binary", default="tailscale")
    plan.add_argument("--model", default="gemini-3.5-flash")
    plan.add_argument("--location", default="us")
    plan.add_argument("--project")
    plan.add_argument("--dataset", default="legacy_migration")

    execute = subparsers.add_parser(
        "execute", help="execute an exact prepared snapshot after approval"
    )
    execute.add_argument("--snapshot", type=Path, required=True)
    execute.add_argument("--digest", required=True)
    execute.add_argument("--approver", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = asyncio.run(_plan(args)) if args.command == "plan" else _execute(args)
    except Exception as exc:
        raise SystemExit(f"M3 canary failed: {exc}") from None
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
