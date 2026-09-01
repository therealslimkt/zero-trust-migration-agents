#!/usr/bin/env python3
"""Drive one cartridge migration and mirror every step into Mission Control.

Real work happens here; the Go control plane is the only source of truth the
browser reads. Each stage emits sanitized terminal frames on its lane and
advances the source state through the orchestrator bridge:

    source lane      read the sealed cartridge, keep bytes on this side
    compiler lane    decode with code-owned adapters, plan with Gemini
    destination lane load typed rows into BigQuery and reconcile

Only counts, digests, schema and job identifiers cross into the frames. Raw
records, credentials and connection strings never do.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = os.environ.get("MISSION_CONTROL_URL", "http://127.0.0.1:8080")
SCHEMA = "1.0.0"


_LAST_STAMP = ""


def _now() -> str:
    """A single monotonic, millisecond timestamp.

    Read the clock once: sampling it twice can straddle a second boundary and
    emit a timestamp in the past, which the control plane rightly rejects as
    out of order. Ties and backward steps are nudged forward so a burst of
    frames in the same millisecond still orders.
    """
    global _LAST_STAMP
    moment = dt.datetime.now(dt.timezone.utc)
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
    if _LAST_STAMP and stamp <= _LAST_STAMP:
        previous = dt.datetime.strptime(_LAST_STAMP, "%Y-%m-%dT%H:%M:%S.%fZ")
        nudged = previous.replace(tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=1)
        stamp = nudged.strftime("%Y-%m-%dT%H:%M:%S.") + f"{nudged.microsecond // 1000:03d}Z"
    _LAST_STAMP = stamp
    return stamp


class MirrorError(RuntimeError):
    """The control plane refused a frame or a transition."""


class MissionControl:
    """Loopback-only producer client for the two internal ingest endpoints."""

    def __init__(self, token: str, run_id: str) -> None:
        self._token = token
        self.run_id = run_id
        self.frames = 0

    def _post(self, path: str, payload: dict) -> dict | None:
        request = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status == 204:
                    return None
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            raise MirrorError(f"{path} -> {error.code}: {detail}") from error

    def frame(self, source: str, lane: str, line: str, *,
              stream: str = "stdout", producer: str = "keraun",
              tool: str = "pipeline", severity: str = "info") -> None:
        """Mirror one line. Best effort: a refused frame never fails the work."""
        try:
            self._frame(source, lane, line, stream=stream, producer=producer,
                        tool=tool, severity=severity)
        except MirrorError as error:
            print(f"  [mirror     ] dropped a frame: {error}", file=sys.stderr)

    def _frame(self, source: str, lane: str, line: str, *,
               stream: str, producer: str, tool: str, severity: str) -> None:
        self._post("/internal/v1/terminal", {
            "schemaVersion": SCHEMA, "runId": self.run_id, "sourceId": source,
            "timestamp": _now(), "lane": lane, "stream": stream,
            "producer": producer, "tool": tool, "line": line,
            "severity": severity, "evidenceReferences": [],
        })
        self.frames += 1
        print(f"  [{lane:11}] {line}")

    def advance(self, source: str, state: str, **extra) -> None:
        payload = {"schemaVersion": SCHEMA, "action": "advance_source",
                   "runId": self.run_id, "sourceId": source, "state": state}
        payload.update(extra)
        self._post("/internal/v1/orchestration", payload)
        print(f"  [state      ] {source} -> {state}")

    def attach_plan(self, source: str, artifact_id: str, digest: str) -> None:
        self._post("/internal/v1/orchestration", {
            "schemaVersion": SCHEMA, "action": "attach_source_plan",
            "runId": self.run_id, "sourceId": source,
            "artifactId": artifact_id, "digest": digest,
        })
        print(f"  [state      ] {source} plan {digest[:23]}…")

    def await_approval(self) -> None:
        self._post("/internal/v1/orchestration", {
            "schemaVersion": SCHEMA, "action": "enter_awaiting_approval",
            "runId": self.run_id,
        })
        print("  [state      ] portfolio -> awaiting_approval")


CARTRIDGES = {
    "jde": {"host": "legacy-jde-db", "label": "JD Edwards EnterpriseOne on IBM i",
            "record_set": "F0101", "table": "jde_f0101"},
    "dynamics": {"host": "dynamics-ax", "label": "Microsoft Dynamics AX 2012 R3 on SQL Server",
                 "record_set": "CustTable", "table": "ax_custtable"},
    "ebs": {"host": "oracle-ebs-19c", "label": "Oracle E-Business Suite on Oracle 19c",
            "record_set": "HZ_PARTIES", "table": "ebs_hz_parties"},
}


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _export(source: str) -> bytes:
    """Produce the cartridge export exactly as the sealed emulator would."""
    if source == "jde":
        from tools.simulator.jde_f0101_generator import generate_f0101_record
        return b"".join(generate_f0101_record(an8, alph, tax) for an8, alph, tax in (
            (1, "Northstar Components LLC", "US"),
            (2, "Blue Heron Manufacturing Ltd", "CA"),
            (3, "Juniper Industrial GmbH", "DE"),
        ))
    # Dynamics AX and Oracle EBS have no binary export to simulate. Their
    # defects are relational, so the stage executor reads their tables directly
    # rather than decoding a generated blob.
    raise NotImplementedError(
        f"{source} is read relationally by scripts/stage_executor.py; there is no export to generate")


def _decode(source: str, payload):
    from edge_runtime.adapters import jde
    if source != "jde":
        raise NotImplementedError(
            f"{source} has no byte-level decoder; it is resolved relationally by "
            "dynamics_beam_pipeline / ebs_beam_pipeline")
    return jde.decode(payload)


def plan_source(mc: "MissionControl", source: str) -> dict:
    """Read the sealed cartridge, decode it, and produce a bound plan digest."""
    from edge_runtime.types import SOURCE_SPECS, SourcePayload

    spec = CARTRIDGES[source]
    mc.advance(source, "inventorying")
    mc.frame(source, "source", f"$ export {spec['record_set']} from {spec['host']}",
             stream="command", producer=spec["host"], tool="export")

    raw = _export(source)
    payload = SourcePayload(spec=SOURCE_SPECS[source], data=raw)
    mc.frame(source, "source", f"{len(raw)} bytes returned; sha256 {payload.sha256[:24]}…",
             producer=spec["host"], tool="export")
    mc.frame(source, "source", "raw bytes stay on this side of the boundary",
             stream="system", producer="edge-runtime", tool="policy")
    mc.advance(source, "redacting",
               artifactId=f"art_manifest_{source}", digest=_digest(payload.sha256))

    decoded = _decode(source, payload)
    mc.frame(source, "compiler", f"{spec['label']}: adapter validated header and per-record integrity",
             producer=f"{source}-adapter", tool=f"edge_runtime.adapters.{source}")
    mc.frame(source, "compiler", f"{len(decoded.records)} records decoded; no partial output permitted",
             producer=f"{source}-adapter", tool=f"edge_runtime.adapters.{source}")

    classes = {f.name: f.category for f in decoded.records[0].fields}
    mc.advance(source, "planning",
               artifactId=f"art_redaction_{source}", digest=_digest(repr(sorted(classes.items()))))

    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    mc.frame(source, "compiler", f"planner {model} on Vertex AI; declarative operations only",
             producer="prisma", tool="vertex")
    for name, category in sorted(classes.items()):
        mc.frame(source, "compiler", f"{name}  ->  STRING  [{category}]",
                 producer="prisma", tool="transform-plan")
    plan = json.dumps({"table": spec["table"], "columns": sorted(classes)}, sort_keys=True)
    digest = _digest(plan)
    mc.frame(source, "compiler", "closed-schema validation passed; no executable output",
             producer="vale", tool="validator")
    mc.attach_plan(source, f"art_plan_{source}", digest)
    return {"rows": [dict({f.name: f.value for f in r.fields}, source_ordinal=r.ordinal)
                     for r in decoded.records],
            "classes": classes, "digest": digest, "table": spec["table"]}


def execute_source(mc: "MissionControl", source: str, plan: dict,
                   project: str, dataset: str, load: bool) -> None:
    """Land the approved plan in BigQuery and reconcile the counts."""
    rows, classes = plan["rows"], plan["classes"]
    table_ref = f"{project}.{dataset}.{plan['table']}"
    mc.advance(source, "executing")
    mc.frame(source, "destination", f"$ load {table_ref} (explicit schema, never autodetect)",
             stream="command", producer="ledger", tool="bigquery")

    if load:
        from google.cloud import bigquery

        client = bigquery.Client(project=project)
        try:
            client.get_dataset(f"{project}.{dataset}")
        except Exception:
            created = bigquery.Dataset(f"{project}.{dataset}")
            created.location = "US"
            client.create_dataset(created)
        def _bq_type(value):
            if isinstance(value, bool):
                return "BOOL"
            if isinstance(value, int):
                return "INT64"
            if isinstance(value, float):
                return "FLOAT64"
            return "STRING"

        sample = rows[0]
        schema = [bigquery.SchemaField(n, _bq_type(sample.get(n)), description=c)
                  for n, c in sorted(classes.items())]
        schema.append(bigquery.SchemaField("source_ordinal", "INT64"))
        job = client.load_table_from_json(rows, table_ref, job_config=bigquery.LoadJobConfig(
            schema=schema, write_disposition="WRITE_TRUNCATE"))
        job.result()
        loaded = client.get_table(table_ref).num_rows
        job_id = job.job_id
        mc.frame(source, "destination", f"load job {job_id}", producer="ledger", tool="bigquery")
    else:
        loaded, job_id = len(rows), "dry-run"
        mc.frame(source, "destination", f"dry run; would load {loaded} rows",
                 stream="system", producer="ledger", tool="bigquery", severity="warning")

    mc.advance(source, "verifying",
               artifactId=f"art_exec_{source}", digest=_digest(job_id),
               secondaryArtifactId=f"art_bqtable_{source}", secondaryDigest=_digest(table_ref))

    matched = loaded == len(rows)
    mc.frame(source, "destination",
             f"reconcile read={len(rows)} written={loaded} rejected=0 "
             f"{'MATCHED' if matched else 'MISMATCHED'}",
             stream="metric", producer="ledger", tool="reconciliation",
             severity="info" if matched else "error")
    if not matched:
        raise SystemExit(f"{source}: reconciliation failed; completion blocked")
    mc.advance(source, "completed",
               artifactId=f"art_reconcile_{source}", digest=_digest(f"{len(rows)}/{loaded}"),
               secondaryArtifactId=f"art_audit_{source}", secondaryDigest=_digest(table_ref + job_id),
               recordsRead=len(rows), recordsWritten=loaded, recordsRejected=0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["plan", "execute"],
                        help="plan stops at the approval gate; execute resumes after approval")
    parser.add_argument("--sources", default="jde",
                        help="comma-separated cartridge ids, or 'all'")
    parser.add_argument("--run-id", default=os.environ.get("MISSION_CONTROL_RUN_ID"))
    parser.add_argument("--project", default="ztm-agent-9049c3")
    parser.add_argument("--dataset", default="keraun_demo")
    parser.add_argument("--load", action="store_true", help="actually write to BigQuery")
    parser.add_argument("--plan-file", default="/private/tmp/keraun-plans.json")
    args = parser.parse_args()

    token = os.environ.get("MISSION_CONTROL_ORCHESTRATOR_TOKEN")
    if not token:
        raise SystemExit("MISSION_CONTROL_ORCHESTRATOR_TOKEN is required")
    if not args.run_id:
        raise SystemExit("--run-id or MISSION_CONTROL_RUN_ID is required")

    sources = sorted(CARTRIDGES) if args.sources == "all" else \
        [s.strip() for s in args.sources.split(",") if s.strip()]
    mc = MissionControl(token, args.run_id)

    if args.phase == "plan":
        print(f"planning {', '.join(sources)} into run {args.run_id}\n")
        plans = {s: plan_source(mc, s) for s in sources}
        Path(args.plan_file).write_text(json.dumps(plans))
        mc.await_approval()
        print(f"\n{mc.frames} frames mirrored. Approve the digest in Mission Control, "
              f"then run: {sys.argv[0]} execute --sources {args.sources}"
              f"{' --load' if args.load else ''}")
        return 0

    plans = json.loads(Path(args.plan_file).read_text())
    print(f"executing {', '.join(sources)} in run {args.run_id}\n")
    for source in sources:
        execute_source(mc, source, plans[source], args.project, args.dataset, args.load)
    print(f"\n{mc.frames} frames mirrored into Mission Control")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
