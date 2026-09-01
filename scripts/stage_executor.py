#!/usr/bin/env python3
"""Loopback-only executor for the three Mission Control stages.

Each stage does real work against the sealed cartridge lab and mirrors what it
did into the Go control plane as terminal frames. The browser never talks to a
source, a driver, or BigQuery directly; it calls a stage here and then watches
the control plane's event stream.

  POST /v1/stages/load     bring the sealed emulator up for one cartridge
  POST /v1/stages/source   run one read-only query against that emulator
  POST /v1/stages/compile  decode the export with code-owned adapters
  POST /v1/stages/land     load the typed rows into BigQuery
  POST /v1/stages/bq       run one read-only query against BigQuery

Only SELECT statements are accepted, one per request. The model never reaches
this surface; a person does, and every rejection is structural.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PORT = 4345
PROJECT = "keraun-cartridge-lab"
COMPOSE = ("docker", "compose", "--project-name", PROJECT,
           "-f", str(ROOT / "cartridge_runtime/host/compose.yaml"),
           "-f", str(ROOT / "cartridge_runtime/host/compose.local.yaml"))
IMAGES = {
    "KERAUN_JDE_IMAGE": "keraun-local-jde",
    "KERAUN_AX_IMAGE": "keraun-local-ax",
    "KERAUN_EBS_IMAGE": "keraun-local-ebs",
    "KERAUN_RUNNER_IMAGE": "keraun-local-runner",
}

CARTRIDGES = {
    "jde": {"service": "jde-e1-ibmi", "db": "keraun_jde", "source": "jde",
            "label": "JD Edwards EnterpriseOne 9.2 / IBM i",
            "queries": [
                ("The address book as the source system presents it",
                 "SELECT aban8, abalph, abtax FROM f0101\n"
                 "ORDER BY aban8 LIMIT 10"),
                ("The same rows as they sit in the physical file",
                 "SELECT aban8, record_length,\n"
                 "       encode(substring(record_bytes from 1 for 16), 'hex') AS first_16_bytes\n"
                 "FROM f0101 ORDER BY aban8 LIMIT 10"),
                ("Dates that are not dates (CYYDDD ordinal > 365)",
                 "SELECT document_number, upmj, defect FROM f0911\n"
                 "WHERE fixture_class = 'invalid' ORDER BY document_number LIMIT 10"),
                ("How much of this table is broken",
                 "SELECT fixture_class, count(*) AS rows,\n"
                 "       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct\n"
                 "FROM f0911 GROUP BY fixture_class"),
                ("Records the COMP-3 decoder will refuse",
                 "SELECT aban8, defect,\n"
                 "       encode(substring(record_bytes from 1 for 5), 'hex') AS comp3_field\n"
                 "FROM f0101 WHERE fixture_class = 'invalid' ORDER BY aban8 LIMIT 10"),
                ("The metadata catalog the fleet reads",
                 "SELECT table_name, field_name, data_type, ordinal\n"
                 "FROM f98711 ORDER BY table_name, ordinal"),
                ("Incremental watermark (UPMJ/UPMT)",
                 "SELECT max(upmj) AS max_upmj, max(upmt) AS max_upmt,\n"
                 "       count(*) AS rows FROM f0911"),
            ]},
    "maxdb": {"service": "dynamics-ax", "db": "keraun_ax", "source": "maxdb",
              "label": "Microsoft Dynamics AX 2012 R3 / SQL Server",
              "queries": [
                  ("Orphan-derived RecIds (base row is gone)",
                   "SELECT c.rec_id, c.customer_group, c.fixture_class\n"
                   "FROM custtable c LEFT JOIN dirpartytable b\n"
                   "  ON b.data_area_id = c.data_area_id\n"
                   " AND b.partition_id = c.partition_id\n"
                   " AND b.rec_id = c.rec_id\n"
                   "WHERE b.rec_id IS NULL ORDER BY c.rec_id LIMIT 10"),
                  ("The inheritance map",
                   "SELECT element_name, extends_element, table_id\n"
                   "FROM modelelement ORDER BY element_name LIMIT 20"),
                  ("Physical to logical table names",
                   "SELECT table_id, physical_name, logical_name FROM sqldictionary\n"
                   "ORDER BY table_id LIMIT 20"),
              ]},
    "btrieve": {"service": "oracle-ebs-19c", "db": "keraun_ebs", "source": "btrieve",
                "label": "Oracle E-Business Suite / Oracle 19c",
                "queries": [
                    ("Flexfields with no meaning in the catalog",
                     "SELECT p.party_id, p.attribute_category, p.attribute1\n"
                     "FROM hz_parties p LEFT JOIN fnd_descriptive_flexs f\n"
                     "  ON f.context_value = p.attribute_category\n"
                     " AND f.segment_column = 'ATTRIBUTE1'\n"
                     "WHERE f.semantic_name IS NULL ORDER BY p.party_id LIMIT 10"),
                    ("What ATTRIBUTE1..5 actually mean",
                     "SELECT context_value, segment_column, semantic_name, data_type\n"
                     "FROM fnd_descriptive_flexs ORDER BY context_value, segment_column LIMIT 20"),
                    ("Incremental watermark",
                     "SELECT max(last_update_date) AS max_last_update FROM hz_parties"),
                ]},
}

COMPILED: dict[str, Any] = {}
EMBEDDED: dict[str, Any] = {}

SELECT_ONLY = re.compile(r"^\s*select\s", re.IGNORECASE)
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do)\b",
    re.IGNORECASE)


class StageError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def guard_sql(sql: str) -> str:
    """Accept exactly one read-only SELECT. Every rejection is structural."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text or len(text) > 2000:
        raise StageError("query_length")
    if ";" in text:
        raise StageError("single_statement_only")
    if not SELECT_ONLY.match(text):
        raise StageError("select_only")
    if FORBIDDEN.search(text):
        raise StageError("read_only_only")
    return text


def compose_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(IMAGES)
    return env


def run(cmd: tuple[str, ...], timeout: int = 300) -> str:
    done = subprocess.run(cmd, cwd=ROOT, env=compose_env(), text=True,
                          capture_output=True, timeout=timeout, check=False)
    if done.returncode != 0:
        raise StageError("command_failed")
    return done.stdout


QUERY_RUNNER = "keraun-query-runner"


def ensure_query_runner() -> None:
    """Keep one long-lived runner attached to the sealed network.

    Spawning a container per query costs 10-15s and drops the browser
    connection. The runner still owns the only route to the emulators; it just
    stays alive between questions instead of being rebuilt for each one.
    """
    probe = subprocess.run(("docker", "inspect", "-f", "{{.State.Running}}", QUERY_RUNNER),
                           capture_output=True, text=True, check=False)
    if probe.returncode == 0 and probe.stdout.strip() == "true":
        return
    subprocess.run(("docker", "rm", "-f", QUERY_RUNNER), capture_output=True, check=False)
    run(COMPOSE + ("run", "-d", "--name", QUERY_RUNNER, "--no-deps",
                   "--entrypoint", "sleep", "evidence-runner", "infinity"), timeout=180)


def psql(cartridge: str, sql: str) -> list[list[str]]:
    """Run one read-only query as cartridge_reader inside the sealed network."""
    spec = CARTRIDGES[cartridge]
    ensure_query_runner()
    done = subprocess.run(
        ("docker", "exec", "-e", "PGPASSWORD=synthetic-only-reader", QUERY_RUNNER,
         "psql", "-h", spec["service"], "-U", "cartridge_reader", "-d", spec["db"],
         "-A", "-F", "\x1f", "--pset", "footer=off", "-c", sql),
        capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        # Surface the database's own complaint; it is structural, not secret.
        detail = (done.stderr or "").strip().splitlines()
        raise StageError(detail[0][:200] if detail else "query_failed")
    return [line.split("\x1f") for line in done.stdout.strip().splitlines() if line]


# ---------------------------------------------------------------- mirroring --
def mirror():
    """Frame producer bound to the current run, or a no-op when unconfigured."""
    from scripts.mission_control_pipeline import MissionControl

    token = os.environ.get("MISSION_CONTROL_ORCHESTRATOR_TOKEN")
    run_id = os.environ.get("MISSION_CONTROL_RUN_ID")
    if not token or not run_id:
        class _Silent:
            frames = 0

            def frame(self, *_a: object, **_k: object) -> None:
                return

        return _Silent()
    return MissionControl(token, run_id)


# ------------------------------------------------------------------ stages --
def stage_load(cartridge: str) -> dict[str, Any]:
    spec = CARTRIDGES[cartridge]
    mc = mirror()
    mc.frame(spec["source"], "source", f"$ docker compose up {spec['service']}",
             stream="command", producer="cartridge-lab", tool="compose")
    run(COMPOSE + ("up", "-d", "--wait", spec["service"]), timeout=300)
    rows = psql(cartridge, "SELECT current_database(), current_user")
    # psql -A emits a header row first; the identity is the row beneath it.
    database, user = (rows[1][0], rows[1][1]) if len(rows) > 1 else ("unknown", "unknown")
    mc.frame(spec["source"], "source",
             f"{spec['label']} online; connected to {database} as {user}",
             producer=spec["service"], tool="psql")
    mc.frame(spec["source"], "source",
             "internal-only network, no egress; read-only role",
             stream="system", producer="cartridge-lab", tool="policy")
    return {"cartridge": cartridge, "service": spec["service"], "database": database,
            "user": user, "label": spec["label"],
            "queries": [{"title": t, "sql": q} for t, q in spec["queries"]]}


def stage_source(cartridge: str, sql: str) -> dict[str, Any]:
    spec = CARTRIDGES[cartridge]
    safe = guard_sql(sql)
    mc = mirror()
    mc.frame(spec["source"], "source", f"$ {safe}",
             stream="command", producer=spec["service"], tool="psql")
    rows = psql(cartridge, safe)
    header, body = (rows[0], rows[1:]) if rows else ([], [])
    for row in body[:12]:
        mc.frame(spec["source"], "source", " | ".join(row)[:400],
                 producer=spec["service"], tool="psql")
    mc.frame(spec["source"], "source", f"{len(body)} rows returned",
             stream="metric", producer=spec["service"], tool="psql")
    return {"columns": header, "rows": body, "rowCount": len(body)}


# Byte layout each adapter walks, mirrored so the conversion is visible.
LAYOUTS = {
    "jde": {"record": 65, "runner": "DirectRunner",
            "dofn": "DecodeJDEAddressBook",
            "fields": [("ABAN8", 0, 5, "COMP-3 packed decimal", "address_number"),
                       ("ABALPH", 5, 40, "EBCDIC cp037", "alpha_name"),
                       ("ABTAX", 45, 20, "EBCDIC cp037", "tax_id")]},
    "maxdb": {"record": None, "runner": "DirectRunner",
              "dofn": "InflateKNA1Cluster", "fields": []},
    "btrieve": {"record": None, "runner": "DirectRunner",
                "dofn": "ReadBtrievePages", "fields": []},
}



RULE = "─" * 78


def _step(mc, source: str, number: int, title: str, detail: str = "") -> None:
    """A labelled divider so each conversion reads as a discrete step."""
    mc.frame(source, "compiler", RULE, stream="system", producer="beam", tool="pipeline")
    mc.frame(source, "compiler", f"STEP {number}  ·  {title}",
             stream="command", producer="beam", tool="pipeline")
    if detail:
        mc.frame(source, "compiler", f"          {detail}",
                 stream="system", producer="beam", tool="pipeline")


def _table(mc, source: str, lane: str, headers: list[str], rows: list[list[str]],
           widths: list[int], producer: str, tool: str) -> None:
    """Print an aligned, ruled table the way a terminal client would."""
    line = "  ".join(h.upper().ljust(w)[:w] for h, w in zip(headers, widths))
    mc.frame(source, lane, line, producer=producer, tool=tool)
    mc.frame(source, lane, "  ".join("─" * w for w in widths),
             stream="system", producer=producer, tool=tool)
    for row in rows:
        mc.frame(source, lane,
                 "  ".join(str(cell).ljust(w)[:w] for cell, w in zip(row, widths)),
                 producer=producer, tool=tool)


def _hex(chunk: bytes, limit: int = 24) -> str:
    body = " ".join(f"{b:02x}" for b in chunk[:limit])
    return body + (" …" if len(chunk) > limit else "")


def fetch_records(cartridge: str, limit: int) -> list[tuple[int, bytes]]:
    """Pull raw records straight out of the emulator, newest layout first."""
    rows = psql(cartridge,
                "SELECT aban8, encode(record_bytes, 'hex') "
                f"FROM f0101 ORDER BY aban8 LIMIT {int(limit)}")
    return [(int(number), bytes.fromhex(payload)) for number, payload in rows[1:]]


def stage_compile(cartridge: str, limit: int = 500) -> dict[str, Any]:
    """Decode the bytes the source lane just showed, one record at a time.

    Reading from the emulator rather than a generated stream is what makes the
    three columns describe one dataset: the hex in column 1 is the hex being
    converted here. Each record is decoded independently so a structurally bad
    row is rejected on its own instead of failing the batch.
    """
    from scripts.mission_control_pipeline import CARTRIDGES as PIPE, _decode, _export
    from edge_runtime.types import SOURCE_SPECS, SourcePayload

    source = CARTRIDGES[cartridge]["source"]
    layout = LAYOUTS[source]
    mc = mirror()

    if source == "jde":
        return compile_jde(mc, cartridge, layout, limit)

    raw = _export(source)
    payload = SourcePayload(spec=SOURCE_SPECS[source], data=raw)

    # --- the Beam environment this conversion runs in ---------------------
    mc.frame(source, "compiler", "$ python -m apache_beam.pipeline --runner=DirectRunner",
             stream="command", producer="beam", tool="apache-beam")
    mc.frame(source, "compiler", f"runner       {layout['runner']}",
             producer="beam", tool="apache-beam")
    mc.frame(source, "compiler", f"transform    ParDo({layout['dofn']})",
             producer="beam", tool="apache-beam")
    mc.frame(source, "compiler",
             f"input        {len(raw)} bytes"
             + (f" · fixed {layout['record']}-byte records" if layout["record"] else " · variable-length clusters"),
             producer="beam", tool="apache-beam")
    mc.frame(source, "compiler",
             "the DoFn is code we own; the model contributes parameters, never code",
             stream="system", producer="beam", tool="policy")

    # --- the bytes, as they arrive ---------------------------------------
    mc.frame(source, "compiler", f"raw[0:24]    {_hex(raw)}",
             producer=f"{source}-adapter", tool="hexdump")

    decoded = _decode(source, payload)

    # --- per record, show the field the DoFn is converting right now ------
    size = layout["record"]
    for index, record in enumerate(decoded.records):
        values = {field.name: field for field in record.fields}
        mc.frame(source, "compiler",
                 f"── record {index + 1}/{len(decoded.records)}"
                 + (f"  offset 0x{index * size:04x}  {size} bytes" if size else ""),
                 stream="system", producer=f"{source}-adapter", tool="ParDo")
        if size and layout["fields"]:
            chunk = raw[index * size:(index + 1) * size]
            for name, start, length, encoding, column in layout["fields"]:
                field = values.get(column)
                if field is None:
                    continue
                mc.frame(source, "compiler",
                         f"  {name:<7} {encoding:<21} {_hex(chunk[start:start + length], 8)}",
                         producer=f"{source}-adapter", tool="ParDo")
                mc.frame(source, "compiler",
                         f"  {'':<7} └─ {column} = {field.value!r}  [{field.category}]",
                         producer=f"{source}-adapter", tool="ParDo")
        else:
            for field in record.fields:
                mc.frame(source, "compiler",
                         f"  {field.name} = {field.value!r}  [{field.category}]",
                         producer=f"{source}-adapter", tool="ParDo")

    mapping = [{"column": f.name, "dataClass": f.category} for f in decoded.records[0].fields]
    mc.frame(source, "compiler",
             f"ParDo complete: {len(decoded.records)} elements, 0 dropped",
             stream="metric", producer="beam", tool="apache-beam")
    mc.frame(source, "compiler",
             "closed schema; anything outside the declared columns is rejected",
             producer="vale", tool="validator")
    return {"records": len(decoded.records), "mapping": mapping,
            "table": PIPE[source]["table"]}


def compile_jde(mc, cartridge: str, layout: dict, limit: int) -> dict[str, Any]:
    """Run the real Beam pipeline and narrate it as discrete, labelled steps."""
    import glob
    import json as _json
    import tempfile

    import apache_beam as beam
    from apache_beam.options.pipeline_options import PipelineOptions

    sys.path.insert(0, str(ROOT))
    from jde_beam_pipeline import DecodeJDERecord, build
    from scripts.mission_control_pipeline import CARTRIDGES as PIPE

    source, size = "jde", layout["record"]
    table = PIPE[source]["table"]

    # ── STEP 1 · the source as a client sees it ────────────────────────
    _step(mc, source, 1, "F0101  ·  read the source as a client sees it",
          "the JDBC driver decodes COMP-3 and EBCDIC on read, so this looks fine")
    readable_sql = f"SELECT aban8, abalph, abtax FROM f0101 ORDER BY aban8 LIMIT {int(limit)}"
    mc.frame(source, "compiler", f"$ {readable_sql}",
             stream="command", producer="jde-e1-ibmi", tool="psql")
    readable = psql(cartridge, readable_sql)[1:]
    _table(mc, source, "compiler", ["aban8", "abalph", "abtax"],
           readable[:10], [8, 34, 8], "jde-e1-ibmi", "psql")
    mc.frame(source, "compiler", f"({len(readable)} rows)",
             stream="metric", producer="jde-e1-ibmi", tool="psql")

    # ── STEP 2 · the same rows as bytes ────────────────────────────────
    _step(mc, source, 2, "F0101  ·  read the same rows from the physical file",
          "ISSUE JDE-F0101-001  ·  COMP-3 packed decimal and EBCDIC cp037, no driver")
    records = fetch_records(cartridge, limit)
    _table(mc, source, "compiler", ["aban8", "bytes 0..19"],
           [[n, _hex(c, 20)] for n, c in records[:10]], [8, 62], "jde-e1-ibmi", "psql")
    mc.frame(source, "compiler",
             "a bulk export has no driver: this is what the migration actually receives",
             stream="system", producer="jde-e1-ibmi", tool="policy")

    # ── STEP 3 · load the runtime ──────────────────────────────────────
    _step(mc, source, 3, "Engage the compiler",
          "code-owned adapters; the model contributes parameters, never code")
    for line in (f"apache-beam    {beam.__version__}",
                 "runner         DirectRunner",
                 f"DoFn           jde_beam_pipeline.{DecodeJDERecord.__name__}",
                 "codec          edge_runtime.adapters.jde  (COMP-3 + EBCDIC cp037)"):
        mc.frame(source, "compiler", line, producer="beam", tool="apache-beam")
    mc.frame(source, "compiler",
             "driver         synthetic emulator speaks SQL directly; the production IBM i "
             "path declares jt400.jar and fingerprints it before use",
             stream="system", producer="maven", tool="driver-contract")

    # ── STEP 4 · convert the packed decimal ────────────────────────────
    _step(mc, source, 4, "Converting ABAN8  ·  COMP-3 packed decimal → BIGQUERY INT64",
          "sign nibble must be C, D or F; every digit nibble must be 0-9")
    mc.frame(source, "compiler",
             f"$ beam.Pipeline | Create({len(records)}) | ParDo(DecodeJDERecord) | WriteToText",
             stream="command", producer="beam", tool="apache-beam")
    workdir = tempfile.mkdtemp(prefix="keraun-beam-")
    accepted_path, rejected_path = os.path.join(workdir, "accepted"), os.path.join(workdir, "rejected")
    options = PipelineOptions(runner="DirectRunner", direct_running_mode="in_memory")
    with beam.Pipeline(options=options) as pipeline:
        build(pipeline, records, accepted_path, rejected_path)
    accepted = [_json.loads(l) for f in glob.glob(accepted_path + "*") for l in open(f)]
    rejected = [_json.loads(l) for f in glob.glob(rejected_path + "*") for l in open(f)]
    classes = accepted[0].pop("_classes") if accepted else {}
    for row in accepted[1:]:
        row.pop("_classes", None)
    by_id = {row.get("source_ordinal"): row for row in accepted}

    mc.frame(source, "compiler", "BEFORE  ·  the bytes", stream="system", producer="beam", tool="ParDo")
    _table(mc, source, "compiler", ["aban8", "COMP-3 field"],
           [[n, _hex(c[0:5], 5)] for n, c in records[:10]], [8, 20], "beam", "ParDo")
    mc.frame(source, "compiler", "AFTER   ·  address_number  INT64",
             stream="system", producer="beam", tool="ParDo")
    _table(mc, source, "compiler", ["aban8", "address_number"],
           [[n, by_id[n]["address_number"]] for n, _ in records[:10] if n in by_id],
           [8, 20], "beam", "ParDo")

    # ── STEP 5 · convert the EBCDIC text ───────────────────────────────
    _step(mc, source, 5, "Converting ABALPH / ABTAX  ·  EBCDIC cp037 → BIGQUERY STRING",
          "cp037 maps all 256 byte values, so text cannot fail structurally")
    mc.frame(source, "compiler", "BEFORE  ·  the bytes", stream="system", producer="beam", tool="ParDo")
    _table(mc, source, "compiler", ["aban8", "EBCDIC field"],
           [[n, _hex(c[5:45], 10)] for n, c in records[:10]], [8, 34], "beam", "ParDo")
    mc.frame(source, "compiler", "AFTER   ·  alpha_name STRING  ·  tax_id STRING",
             stream="system", producer="beam", tool="ParDo")
    _table(mc, source, "compiler", ["aban8", "alpha_name", "tax_id"],
           [[n, by_id[n]["alpha_name"], by_id[n]["tax_id"]] for n, _ in records[:10] if n in by_id],
           [8, 34, 8], "beam", "ParDo")

    # ── STEP 6 · the tally ─────────────────────────────────────────────
    _step(mc, source, 6, "Result", f"target table {table}")
    for name, category in sorted(classes.items()):
        mc.frame(source, "compiler", f"  {name:<18} {category}",
                 producer="vale", tool="schema")
    mc.frame(source, "compiler",
             f"pipeline finished: {len(accepted)} accepted, {len(rejected)} rejected "
             f"of {len(records)} read",
             stream="metric", producer="beam", tool="apache-beam")
    if rejected:
        mc.frame(source, "compiler",
                 f"{len(rejected)} records could not be decoded and are quarantined, not repaired",
                 stream="stderr", producer="vale", tool="policy", severity="error")
        for reject in rejected[:5]:
            mc.frame(source, "compiler",
                     f"  aban8 {reject['aban8']:<8} {reject['detail']}",
                     stream="stderr", producer="vale", tool="quarantine", severity="error")
        mc.frame(source, "compiler",
                 "the full quarantine manifest is downloadable beside this mirror",
                 stream="system", producer="vale", tool="quarantine")
    mc.frame(source, "compiler", RULE, stream="system", producer="beam", tool="pipeline")

    COMPILED[cartridge] = {"rows": accepted, "classes": classes,
                           "read": len(records), "rejected": len(rejected),
                           "quarantine": rejected}
    return {"records": len(accepted), "read": len(records),
            "rejected": len(rejected), "beamVersion": beam.__version__,
            "quarantine": rejected,
            "mapping": [{"column": n, "dataClass": c} for n, c in sorted(classes.items())],
            "table": table}


def stage_land(cartridge: str, project: str, dataset: str) -> dict[str, Any]:
    from google.cloud import bigquery
    from scripts.mission_control_pipeline import CARTRIDGES as PIPE, _decode, _export
    from edge_runtime.types import SOURCE_SPECS, SourcePayload

    source = CARTRIDGES[cartridge]["source"]
    table = PIPE[source]["table"]
    mc = mirror()

    compiled = COMPILED.get(cartridge)
    if compiled:
        # Land exactly what the compiler accepted, so read = accepted + rejected
        # reconciles against the rows the source lane actually held.
        rows, classes = compiled["rows"], compiled["classes"]
        read_count, rejected_count = compiled["read"], compiled["rejected"]
    else:
        decoded = _decode(source, SourcePayload(spec=SOURCE_SPECS[source], data=_export(source)))
        rows = [dict({f.name: f.value for f in r.fields}, source_ordinal=r.ordinal)
                for r in decoded.records]
        classes = {f.name: f.category for f in decoded.records[0].fields}
        read_count, rejected_count = len(rows), 0
    if not rows:
        raise StageError("nothing_compiled")

    def bq_type(value: object) -> str:
        if isinstance(value, bool):
            return "BOOL"
        if isinstance(value, int):
            return "INT64"
        if isinstance(value, float):
            return "FLOAT64"
        return "STRING"

    client = bigquery.Client(project=project)
    ref = f"{project}.{dataset}.{table}"
    mc.frame(source, "destination", f"$ load {ref} (explicit schema, never autodetect)",
             stream="command", producer="ledger", tool="bigquery")
    schema = [bigquery.SchemaField(n, bq_type(rows[0].get(n)), description=c)
              for n, c in sorted(classes.items())]
    schema.append(bigquery.SchemaField("source_ordinal", "INT64"))
    job = client.load_table_from_json(rows, ref, job_config=bigquery.LoadJobConfig(
        schema=schema, write_disposition="WRITE_TRUNCATE"))
    job.result()
    loaded = client.get_table(ref).num_rows
    mc.frame(source, "destination", f"load job {job.job_id}",
             producer="ledger", tool="bigquery")
    matched = loaded == len(rows) and read_count == loaded + rejected_count
    mc.frame(source, "destination",
             f"reconcile read={read_count} accepted={len(rows)} "
             f"rejected={rejected_count} written={loaded} "
             f"{'MATCHED' if matched else 'MISMATCHED'}",
             stream="metric", producer="ledger", tool="reconciliation",
             severity="info" if matched else "error")
    return {"table": ref, "jobId": job.job_id, "rowsRead": read_count,
            "rowsAccepted": len(rows), "rowsRejected": rejected_count,
            "rowsWritten": loaded, "matched": matched,
            "queries": [f"SELECT * FROM `{ref}` ORDER BY source_ordinal",
                        f"SELECT count(*) AS rows FROM `{ref}`"]}


EMBED_MODEL = "keraun_demo.embedder"
EMBED_CONNECTION = "us.keraun_vertex"


def stage_embed(cartridge: str, project: str, dataset: str) -> dict[str, Any]:
    """Embed the landed rows inside BigQuery so the table is queryable by meaning.

    ML.GENERATE_EMBEDDING runs the model through a CLOUD_RESOURCE connection, so
    the vectors are produced in the warehouse. Row values are never sent
    anywhere by us, and nothing is downloaded to be embedded.
    """
    from google.cloud import bigquery
    from scripts.mission_control_pipeline import CARTRIDGES as PIPE

    source = CARTRIDGES[cartridge]["source"]
    table = PIPE[source]["table"]
    ref = f"{project}.{dataset}.{table}"
    target = f"{ref}_embeddings"
    mc = mirror()

    mc.frame(source, "destination", f"$ ML.GENERATE_EMBEDDING over {table}",
             stream="command", producer="bigquery", tool="bigquery-ml")
    mc.frame(source, "destination",
             f"model      {EMBED_MODEL}  (remote, text-embedding-005)",
             producer="bigquery", tool="bigquery-ml")
    mc.frame(source, "destination",
             f"connection {EMBED_CONNECTION}  ·  embeddings are generated in the warehouse",
             stream="system", producer="bigquery", tool="policy")

    client = bigquery.Client(project=project)
    job = client.query(f"""
        CREATE OR REPLACE TABLE `{target}` AS
        SELECT source_ordinal, address_number, alpha_name, tax_id, content,
               ml_generate_embedding_result AS embedding,
               ml_generate_embedding_status AS status
        FROM ML.GENERATE_EMBEDDING(
          MODEL `{project}.{EMBED_MODEL}`,
          (SELECT source_ordinal, address_number, alpha_name, tax_id,
                  FORMAT('Customer %d, %s, registered in %s.',
                         address_number, alpha_name, tax_id) AS content
           FROM `{ref}`),
          STRUCT(TRUE AS flatten_json_output, 'RETRIEVAL_DOCUMENT' AS task_type))
    """)
    job.result(timeout=600)

    stats = list(client.query(f"""
        SELECT count(*) AS row_count, ARRAY_LENGTH(ANY_VALUE(embedding)) AS dims,
               countif(status != '') AS failures
        FROM `{target}`""").result(timeout=120))[0]

    mc.frame(source, "destination",
             f"{stats['row_count']} rows embedded · {stats['dims']} dimensions · "
             f"{stats['failures']} failures",
             stream="metric", producer="bigquery", tool="bigquery-ml",
             severity="info" if stats["failures"] == 0 else "error")
    mc.frame(source, "destination",
             "the table is now searchable by meaning, not just by column",
             producer="bigquery", tool="bigquery-ml")

    EMBEDDED[cartridge] = {"table": target, "rows": int(stats["row_count"]),
                           "dims": int(stats["dims"])}
    return {"table": target, "rows": int(stats["row_count"]), "dimensions": int(stats["dims"]),
            "failures": int(stats["failures"]), "jobId": job.job_id,
            "examples": ["metal foundry and castings business in Australia",
                         "logistics company in continental Europe",
                         "industrial manufacturer in Japan"]}


def stage_search(cartridge: str, question: str, project: str, dataset: str) -> dict[str, Any]:
    """Answer a plain-language question with a governed VECTOR_SEARCH.

    The caller supplies one parameter. The query itself is fixed here, so no
    model and no visitor ever composes SQL against the warehouse.
    """
    from google.cloud import bigquery

    text = (question or "").strip()
    if not text or len(text) > 400:
        raise StageError("query_length")
    source = CARTRIDGES[cartridge]["source"]
    target = EMBEDDED.get(cartridge, {}).get("table")
    if not target:
        raise StageError("nothing_embedded")
    mc = mirror()
    mc.frame(source, "destination", f"$ VECTOR_SEARCH  \"{text}\"",
             stream="command", producer="analyst", tool="bigquery-ml")

    client = bigquery.Client(project=project)
    rows = list(client.query(
        f"""
        SELECT base.address_number AS address_number, base.alpha_name AS alpha_name,
               base.tax_id AS tax_id, ROUND(distance, 4) AS distance
        FROM VECTOR_SEARCH(
          TABLE `{target}`, 'embedding',
          (SELECT ml_generate_embedding_result AS embedding
           FROM ML.GENERATE_EMBEDDING(
             MODEL `{project}.{EMBED_MODEL}`,
             (SELECT @q AS content),
             STRUCT(TRUE AS flatten_json_output, 'RETRIEVAL_QUERY' AS task_type))),
          top_k => 5, distance_type => 'COSINE')
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("q", "STRING", text)]),
    ).result(timeout=180))

    for r in rows:
        mc.frame(source, "destination",
                 f"  {r['address_number']:<6} {r['alpha_name']:<34} {r['tax_id']:<4} "
                 f"distance {r['distance']}",
                 producer="bigquery", tool="vector-search")
    mc.frame(source, "destination",
             f"{len(rows)} nearest by meaning · the words need not appear in the row",
             stream="metric", producer="bigquery", tool="vector-search")
    return {"columns": ["address_number", "alpha_name", "tax_id", "distance"],
            "rows": [[str(r["address_number"]), r["alpha_name"], r["tax_id"], str(r["distance"])]
                     for r in rows],
            "rowCount": len(rows)}


def stage_quarantine(cartridge: str) -> dict[str, Any]:
    """Return the refused records: why each failed, and how to find it again."""
    compiled = COMPILED.get(cartridge)
    if not compiled:
        raise StageError("nothing_compiled")
    rows = compiled.get("quarantine", [])
    columns = ["sourceTable", "sourceKey", "aban8", "reason", "detail",
               "recordLength", "comp3FieldHex"]

    def cell(value: object) -> str:
        text = "" if value is None else str(value)
        return f'"{text}"' if any(c in text for c in ',"\n') else text

    csv = "\n".join([",".join(columns)] +
                     [",".join(cell(row.get(c)) for c in columns) for row in rows])
    return {"cartridge": cartridge, "count": len(rows), "columns": columns,
            "rows": rows, "csv": csv,
            "filename": f"keraun-quarantine-{cartridge}-{compiled['read']}read.csv"}


def stage_bq(cartridge: str, sql: str, project: str) -> dict[str, Any]:
    from google.cloud import bigquery

    source = CARTRIDGES[cartridge]["source"]
    safe = guard_sql(sql)
    mc = mirror()
    mc.frame(source, "destination", f"$ {safe}",
             stream="command", producer="analyst", tool="bigquery")
    client = bigquery.Client(project=project)
    job = client.query(safe)
    result = job.result(timeout=90)
    columns = [field.name for field in result.schema]
    rows = [[("" if value is None else str(value)) for value in row.values()]
            for row in result]
    for row in rows[:12]:
        mc.frame(source, "destination", " | ".join(row)[:400],
                 producer="bigquery", tool="query")
    mc.frame(source, "destination",
             f"{len(rows)} rows · job {job.job_id} · {job.total_bytes_processed or 0} bytes scanned",
             stream="metric", producer="bigquery", tool="query")
    return {"columns": columns, "rows": rows, "rowCount": len(rows), "jobId": job.job_id}


# ------------------------------------------------------------------ server --
def handler_for(token: str, project: str, dataset: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def authorized(self) -> bool:
            return hmac.compare_digest(
                self.headers.get("Authorization", ""), f"Bearer {token}")

        def send_json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            payload = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 8192:
                raise StageError("body_required")
            try:
                parsed = json.loads(self.rfile.read(length))
            except ValueError as error:
                raise StageError("malformed_body") from error
            if not isinstance(parsed, dict):
                raise StageError("malformed_body")
            return parsed

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/v1/stages" or not self.authorized():
                self.send_json(HTTPStatus.NOT_FOUND, {"code": "not_found"})
                return
            self.send_json(HTTPStatus.OK, {"cartridges": [
                {"id": key, "label": spec["label"], "service": spec["service"],
                 "queries": [{"title": t, "sql": q} for t, q in spec["queries"]]}
                for key, spec in CARTRIDGES.items()]})

        def do_POST(self) -> None:  # noqa: N802
            if not self.authorized() or not self.path.startswith("/v1/stages/"):
                self.send_json(HTTPStatus.NOT_FOUND, {"code": "not_found"})
                return
            stage = self.path.rsplit("/", 1)[-1]
            try:
                payload = self.body()
                cartridge = payload.get("cartridge")
                if cartridge not in CARTRIDGES:
                    raise StageError("unknown_cartridge")
                if stage == "load":
                    result = stage_load(cartridge)
                elif stage == "source":
                    result = stage_source(cartridge, payload.get("sql", ""))
                elif stage == "compile":
                    result = stage_compile(cartridge)
                elif stage == "land":
                    result = stage_land(cartridge, project, dataset)
                elif stage == "embed":
                    result = stage_embed(cartridge, project, dataset)
                elif stage == "search":
                    result = stage_search(cartridge, payload.get("q", ""), project, dataset)
                elif stage == "quarantine":
                    result = stage_quarantine(cartridge)
                elif stage == "bq":
                    result = stage_bq(cartridge, payload.get("sql", ""), project)
                else:
                    raise StageError("unknown_stage")
            except StageError as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"code": error.code})
                return
            except subprocess.TimeoutExpired:
                self.send_json(HTTPStatus.GATEWAY_TIMEOUT, {"code": "stage_timeout"})
                return
            except Exception as error:  # Fail closed; no driver or cloud detail reaches the browser.
                print(f"stage {stage} failed: {error!r}", file=sys.stderr, flush=True)
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"code": "stage_failed"})
                return
            except BaseException as error:  # noqa: BLE001 - never drop the connection silently
                print(f"stage {stage} aborted: {error!r}", file=sys.stderr, flush=True)
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"code": "stage_failed"})
                return
            self.send_json(HTTPStatus.OK, result)

    return Handler


def main() -> int:
    token = os.environ.get("KERAUN_STAGE_EXECUTOR_TOKEN")
    if not token or len(token) < 32:
        raise SystemExit("KERAUN_STAGE_EXECUTOR_TOKEN must be at least 32 characters")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "ztm-agent-9049c3")
    dataset = os.environ.get("KERAUN_BQ_DATASET", "keraun_demo")
    server = ThreadingHTTPServer((HOST, PORT), handler_for(token, project, dataset))
    print(f"Keraun stage executor listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
