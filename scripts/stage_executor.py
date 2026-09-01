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
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Loopback by default so a local run is never reachable off-box. The hosted
# cartridge lab sets this to its VPC address so Cloud Run can reach it.
HOST = os.environ.get("KERAUN_STAGE_EXECUTOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("KERAUN_STAGE_EXECUTOR_PORT", "4345"))
PROJECT = "keraun-cartridge-lab"
# The local preflight stacks compose.local.yaml on top to swap gVisor for runc,
# because Docker Desktop has no runsc. The hosted lab runs the real thing and
# must not inherit that override, so the file list is host-configurable.
_COMPOSE_FILES = tuple(
    part for part in os.environ.get("KERAUN_COMPOSE_FILES", "").split(":") if part
) or (
    str(ROOT / "cartridge_runtime/host/compose.yaml"),
    str(ROOT / "cartridge_runtime/host/compose.local.yaml"),
)
COMPOSE = ("docker", "compose", "--project-name", PROJECT) + tuple(
    argument for path in _COMPOSE_FILES for argument in ("-f", path))
IMAGES = {
    "KERAUN_JDE_IMAGE": "keraun-local-jde",
    "KERAUN_AX_IMAGE": "keraun-local-ax",
    "KERAUN_EBS_IMAGE": "keraun-local-ebs",
    "KERAUN_RUNNER_IMAGE": "keraun-local-runner",
}

CARTRIDGES = {
    "jde": {"service": "jde-e1-ibmi", "db": "keraun_jde", "source": "jde", "addr": "172.28.0.11",
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
    "dynamics": {"service": "dynamics-ax", "db": "keraun_ax", "source": "dynamics", "addr": "172.28.0.12",
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
    "ebs": {"service": "oracle-ebs-19c", "db": "keraun_ebs", "source": "ebs", "addr": "172.28.0.13",
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
    """Compose needs image refs; the host's own pins take precedence.

    compose.yaml declares every image with `:?digest-pinned image required`, so
    a host that pins digest-addressed images must be able to supply them. These
    are defaults for the local preflight, not overrides.
    """
    env = dict(os.environ)
    for key, default in IMAGES.items():
        env.setdefault(key, default)
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
    """Run one read-only query as cartridge_reader inside the sealed network.

    Addressed by the static IP compose pins rather than the service name.
    cartridge-internal is an internal network with fixed ipv4_address entries,
    and the embedded resolver is not reachable from the locked-down runner on
    every host, so the name lookup is the one part of this that is not portable.
    compose.yaml already hands the evidence runner these same addresses.
    """
    spec = CARTRIDGES[cartridge]
    ensure_query_runner()
    done = subprocess.run(
        ("docker", "exec", "-e", "PGPASSWORD=synthetic-only-reader", QUERY_RUNNER,
         "psql", "-h", spec["addr"], "-U", "cartridge_reader", "-d", spec["db"],
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
    # Neither of these decodes bytes. AX hides a logical row across two physical
    # tables, and EBS hides a column's meaning in a metadata catalogue, so the
    # transform is a join and a lookup rather than an unpack.
    "dynamics": {"record": None, "runner": "DirectRunner",
                 "dofn": "ResolveAXInheritance", "fields": []},
    "ebs": {"record": None, "runner": "DirectRunner",
            "dofn": "ResolveDescriptiveFlexfield", "fields": []},
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
    """Decode the rows the source lane just showed, one record at a time.

    Reading from the emulator rather than a generated stream is what makes the
    three columns describe one dataset: the rows in column 1 are the rows being
    converted here. Each record is decoded independently so a bad row is
    rejected on its own instead of failing the batch.
    """
    source = CARTRIDGES[cartridge]["source"]
    layout = LAYOUTS[source]
    mc = mirror()

    if source == "jde":
        return compile_jde(mc, cartridge, layout, limit)
    if source == "dynamics":
        return compile_dynamics(mc, cartridge, layout, limit)
    if source == "ebs":
        return compile_ebs(mc, cartridge, layout, limit)
    raise StageError(f"no_compiler_for_{source}")


def _run_beam(build_call) -> tuple[list[dict], list[dict]]:
    """Execute one DirectRunner pipeline and read both tagged outputs back."""
    import glob
    import json as _json
    import tempfile

    import apache_beam as beam
    from apache_beam.options.pipeline_options import PipelineOptions

    workdir = tempfile.mkdtemp(prefix="keraun-beam-")
    accepted_path = os.path.join(workdir, "accepted")
    rejected_path = os.path.join(workdir, "rejected")
    options = PipelineOptions(runner="DirectRunner", direct_running_mode="in_memory")
    with beam.Pipeline(options=options) as pipeline:
        build_call(pipeline, accepted_path, rejected_path)
    accepted = [_json.loads(line) for f in glob.glob(accepted_path + "*") for line in open(f)]
    rejected = [_json.loads(line) for f in glob.glob(rejected_path + "*") for line in open(f)]
    return accepted, rejected


def _finish(mc, source: str, cartridge: str, table: str, accepted: list[dict],
            rejected: list[dict], read: int, beam_version: str,
            quarantine_label) -> dict[str, Any]:
    """Shared tally, quarantine narration and COMPILED handoff."""
    # Take the union, not the first row's view. EBS resolves ATTRIBUTE1 against
    # the row's own context, so a CUSTOMER_EXT row lands customer_tier while a
    # SUPPLIER_EXT row lands payment_profile. Reading the schema off row one
    # would silently drop every column the first row happened not to carry.
    classes: dict[str, str] = {}
    for row in accepted:
        classes.update(row.pop("_classes", {}))

    _step(mc, source, 6, "Result", f"target table {table}")
    for name, category in sorted(classes.items()):
        mc.frame(source, "compiler", f"  {name:<18} {category}",
                 producer="vale", tool="schema")
    mc.frame(source, "compiler",
             f"pipeline finished: {len(accepted)} accepted, {len(rejected)} rejected "
             f"of {read} read",
             stream="metric", producer="beam", tool="apache-beam")
    if rejected:
        mc.frame(source, "compiler",
                 f"{len(rejected)} records could not be resolved and are quarantined, not repaired",
                 stream="stderr", producer="vale", tool="policy", severity="error")
        for reject in rejected[:5]:
            mc.frame(source, "compiler", f"  {quarantine_label(reject)}",
                     stream="stderr", producer="vale", tool="quarantine", severity="error")
        mc.frame(source, "compiler",
                 "the full quarantine manifest is downloadable beside this mirror",
                 stream="system", producer="vale", tool="quarantine")
    mc.frame(source, "compiler", RULE, stream="system", producer="beam", tool="pipeline")

    COMPILED[cartridge] = {"rows": accepted, "classes": classes,
                           "read": read, "rejected": len(rejected),
                           "quarantine": rejected}
    return {"records": len(accepted), "read": read,
            "rejected": len(rejected), "beamVersion": beam_version,
            "quarantine": rejected,
            "mapping": [{"column": n, "dataClass": c} for n, c in sorted(classes.items())],
            "table": table}


def compile_dynamics(mc, cartridge: str, layout: dict, limit: int) -> dict[str, Any]:
    """Resolve AX table inheritance and narrate it as discrete, labelled steps."""
    import apache_beam as beam

    from dynamics_beam_pipeline import ResolveAXInheritance, build
    from scripts.mission_control_pipeline import CARTRIDGES as PIPE

    source, table = "dynamics", PIPE["dynamics"]["table"]
    cap = int(limit)

    # -- STEP 1 - the entity as a client sees it -------------------------
    _step(mc, source, 1, "CustTable  ·  read the entity as a client sees it",
          "the application layer joins the inheritance for you, so this looks like one table")
    joined_sql = ("SELECT c.data_area_id, c.partition_id, c.rec_id, b.party_name, c.customer_group\n"
                  "FROM custtable c JOIN dirpartytable b\n"
                  "  ON b.data_area_id = c.data_area_id\n"
                  " AND b.partition_id = c.partition_id\n"
                  " AND b.rec_id = c.rec_id\n"
                  f"ORDER BY c.rec_id LIMIT {cap}")
    mc.frame(source, "compiler", f"$ {joined_sql}",
             stream="command", producer="dynamics-ax", tool="psql")
    joined = psql(cartridge, joined_sql)[1:]
    _table(mc, source, "compiler", ["company", "partition", "rec_id", "party_name", "group"],
           joined[:10], [9, 12, 8, 24, 12], "dynamics-ax", "psql")
    mc.frame(source, "compiler", f"({len(joined)} rows)",
             stream="metric", producer="dynamics-ax", tool="psql")

    # -- STEP 2 - the same entity as two physical tables ------------------
    _step(mc, source, 2, "CustTable + DirPartyTable  ·  read the physical tables",
          "ISSUE AX-CUSTTABLE-001  ·  a derived row is only valid beside its base row")
    derived_sql = ("SELECT data_area_id, partition_id, rec_id, customer_group, modified_datetime\n"
                   f"FROM custtable ORDER BY rec_id, partition_id LIMIT {cap}")
    base_sql = ("SELECT data_area_id, partition_id, rec_id, party_name, modified_datetime\n"
                f"FROM dirpartytable ORDER BY rec_id, partition_id LIMIT {cap}")
    mc.frame(source, "compiler", f"$ {derived_sql}",
             stream="command", producer="dynamics-ax", tool="psql")
    derived_rows_raw = psql(cartridge, derived_sql)[1:]
    _table(mc, source, "compiler", ["company", "partition", "rec_id", "group"],
           [r[:4] for r in derived_rows_raw[:10]], [9, 12, 8, 12], "dynamics-ax", "psql")
    mc.frame(source, "compiler", f"$ {base_sql}",
             stream="command", producer="dynamics-ax", tool="psql")
    base_rows_raw = psql(cartridge, base_sql)[1:]
    _table(mc, source, "compiler", ["company", "partition", "rec_id", "party_name"],
           [r[:4] for r in base_rows_raw[:10]], [9, 12, 8, 24], "dynamics-ax", "psql")
    mc.frame(source, "compiler",
             "a bulk export has no application layer: this is what the migration actually receives",
             stream="system", producer="dynamics-ax", tool="policy")

    derived_rows = [{"data_area_id": r[0], "partition_id": int(r[1]), "rec_id": int(r[2]),
                     "customer_group": r[3], "modified_datetime": r[4]}
                    for r in derived_rows_raw]
    base_rows = [{"data_area_id": r[0], "partition_id": int(r[1]), "rec_id": int(r[2]),
                  "party_name": r[3], "modified_datetime": r[4]}
                 for r in base_rows_raw]

    # -- STEP 3 - load the runtime ---------------------------------------
    _step(mc, source, 3, "Engage the compiler",
          "code-owned transform; the model contributes parameters, never code")
    for line in (f"apache-beam    {beam.__version__}",
                 "runner         DirectRunner",
                 f"DoFn           dynamics_beam_pipeline.{ResolveAXInheritance.__name__}",
                 "join           CoGroupByKey on (DataAreaId, PartitionId, RecId)"):
        mc.frame(source, "compiler", line, producer="beam", tool="apache-beam")
    mc.frame(source, "compiler",
             "driver         synthetic emulator speaks SQL directly; the production AX "
             "path declares mssql-jdbc.jar and fingerprints it before use",
             stream="system", producer="maven", tool="driver-contract")

    # -- STEP 4 - resolve the inheritance --------------------------------
    _step(mc, source, 4, "Resolving CustTable → DirPartyTable  ·  table inheritance",
          "RecId is not an identity on its own; the join must hold company and partition")
    mc.frame(source, "compiler",
             f"$ beam.Pipeline | Create({len(derived_rows)}) + Create({len(base_rows)}) "
             "| CoGroupByKey | ParDo(ResolveAXInheritance) | WriteToText",
             stream="command", producer="beam", tool="apache-beam")
    accepted, rejected = _run_beam(
        lambda pipeline, a, r: build(pipeline, derived_rows, base_rows, a, r))
    by_key = {(row["data_area_id"], row["partition_id"], row["rec_id"]): row
              for row in accepted}

    mc.frame(source, "compiler", "BEFORE  ·  the derived row alone",
             stream="system", producer="beam", tool="ParDo")
    _table(mc, source, "compiler", ["company", "partition", "rec_id", "group"],
           [[r["data_area_id"], r["partition_id"], r["rec_id"], r["customer_group"]]
            for r in derived_rows[:10]], [9, 12, 8, 12], "beam", "ParDo")
    mc.frame(source, "compiler", "AFTER   ·  party_name inherited from the base row",
             stream="system", producer="beam", tool="ParDo")
    _table(mc, source, "compiler", ["company", "partition", "rec_id", "party_name", "group"],
           [[r["data_area_id"], r["partition_id"], r["rec_id"],
             by_key[(r["data_area_id"], r["partition_id"], r["rec_id"])]["party_name"],
             r["customer_group"]]
            for r in derived_rows[:10]
            if (r["data_area_id"], r["partition_id"], r["rec_id"]) in by_key],
           [9, 12, 8, 24, 12], "beam", "ParDo")

    # -- STEP 5 - name the object ----------------------------------------
    _step(mc, source, 5, "Resolving the AX object name  ·  SQLDICTIONARY + MODELELEMENT",
          "the physical table name is not the application's name for the entity")
    catalog_sql = ("SELECT m.element_name, m.extends_element, d.physical_name\n"
                   "FROM modelelement m JOIN sqldictionary d ON d.table_id = m.table_id\n"
                   "ORDER BY m.element_name LIMIT 20")
    mc.frame(source, "compiler", f"$ {catalog_sql}",
             stream="command", producer="dynamics-ax", tool="psql")
    _table(mc, source, "compiler", ["element", "extends", "physical"],
           psql(cartridge, catalog_sql)[1:], [18, 18, 18], "dynamics-ax", "psql")

    return _finish(mc, source, cartridge, table, accepted, rejected, len(derived_rows),
                   beam.__version__,
                   lambda reject: (f"rec_id {reject['recId']:<8} "
                                   f"{reject['dataAreaId']}/{reject['partitionId']}  "
                                   f"{reject['reason']}"))


def compile_ebs(mc, cartridge: str, layout: dict, limit: int) -> dict[str, Any]:
    """Resolve EBS descriptive flexfields and narrate it as discrete, labelled steps."""
    import apache_beam as beam

    from ebs_beam_pipeline import GENERIC_COLUMNS, ResolveDescriptiveFlexfield, build
    from scripts.mission_control_pipeline import CARTRIDGES as PIPE

    source, table = "ebs", PIPE["ebs"]["table"]
    cap = int(limit)

    # -- STEP 1 - the rows as a client sees them -------------------------
    _step(mc, source, 1, "HZ_PARTIES  ·  read the rows as a client sees them",
          "the application resolves the flexfield for you, so these columns look named")
    party_sql = ("SELECT party_id, party_name, attribute_category, attribute1, attribute2,\n"
                 "       last_update_date\n"
                 f"FROM hz_parties ORDER BY party_id LIMIT {cap}")
    mc.frame(source, "compiler", f"$ {party_sql}",
             stream="command", producer="oracle-ebs-19c", tool="psql")
    party_raw = psql(cartridge, party_sql)[1:]
    _table(mc, source, "compiler",
           ["party_id", "party_name", "context", "attribute1", "attribute2"],
           [r[:5] for r in party_raw[:10]], [9, 20, 16, 12, 12], "oracle-ebs-19c", "psql")
    mc.frame(source, "compiler", f"({len(party_raw)} rows)",
             stream="metric", producer="oracle-ebs-19c", tool="psql")

    # -- STEP 2 - the column that means two things -----------------------
    _step(mc, source, 2, "HZ_PARTIES  ·  ATTRIBUTE1 does not mean one thing",
          "ISSUE EBS-HZPARTIES-001  ·  the meaning lives in the catalogue, not the column")
    flex_sql = ("SELECT context_value, segment_column, semantic_name, data_type,\n"
                "       metadata_version\n"
                "FROM fnd_descriptive_flexs ORDER BY context_value, segment_column LIMIT 40")
    mc.frame(source, "compiler", f"$ {flex_sql}",
             stream="command", producer="oracle-ebs-19c", tool="psql")
    flex_raw = psql(cartridge, flex_sql)[1:]
    _table(mc, source, "compiler",
           ["context", "segment", "semantic_name", "type", "metadata_version"],
           flex_raw[:20], [16, 12, 20, 8, 20], "oracle-ebs-19c", "psql")
    mc.frame(source, "compiler",
             "ATTRIBUTE1 is a different column in every context; copying it across "
             "preserves the bytes and loses the meaning",
             stream="system", producer="oracle-ebs-19c", tool="policy")

    party_rows = [{"party_id": int(r[0]), "party_name": r[1], "attribute_category": r[2],
                   "attribute1": r[3] or None, "attribute2": r[4] or None,
                   "attribute3": None, "attribute4": None, "attribute5": None,
                   "last_update_date": r[5]}
                  for r in party_raw]
    flex_map = {(r[0], r[1]): (r[2], r[3]) for r in flex_raw}
    metadata_version = flex_raw[0][4] if flex_raw else "unknown"

    # -- STEP 3 - load the runtime ---------------------------------------
    _step(mc, source, 3, "Engage the compiler",
          "code-owned transform; the model contributes parameters, never code")
    for line in (f"apache-beam    {beam.__version__}",
                 "runner         DirectRunner",
                 f"DoFn           ebs_beam_pipeline.{ResolveDescriptiveFlexfield.__name__}",
                 f"catalogue      FND_DESCRIPTIVE_FLEXS @ {metadata_version}"):
        mc.frame(source, "compiler", line, producer="beam", tool="apache-beam")
    mc.frame(source, "compiler",
             "driver         synthetic emulator speaks SQL directly; the production EBS "
             "path declares ojdbc8.jar and fingerprints it before use",
             stream="system", producer="maven", tool="driver-contract")

    # -- STEP 4 - resolve the flexfields ---------------------------------
    _step(mc, source, 4, "Resolving ATTRIBUTE1..5  ·  descriptive flexfield → named columns",
          "a context with no mapping is quarantined rather than landed untyped")
    mc.frame(source, "compiler",
             f"$ beam.Pipeline | Create({len(party_rows)}) "
             "| ParDo(ResolveDescriptiveFlexfield) | WriteToText",
             stream="command", producer="beam", tool="apache-beam")
    accepted, rejected = _run_beam(
        lambda pipeline, a, r: build(pipeline, party_rows, flex_map, metadata_version, a, r))
    by_id = {row["party_id"]: row for row in accepted}

    mc.frame(source, "compiler", "BEFORE  ·  generic columns",
             stream="system", producer="beam", tool="ParDo")
    _table(mc, source, "compiler", ["party_id", "context", "attribute1", "attribute2"],
           [[r["party_id"], r["attribute_category"], r["attribute1"], r["attribute2"]]
            for r in party_rows[:10]], [9, 16, 14, 14], "beam", "ParDo")
    mc.frame(source, "compiler", "AFTER   ·  the same values under their declared names",
             stream="system", producer="beam", tool="ParDo")
    for row in party_rows[:10]:
        landed = by_id.get(row["party_id"])
        if landed is None:
            continue
        named = [f"{k} = {v!r}" for k, v in landed.items()
                 if k not in ("_classes", "source_ordinal", "party_id", "party_name",
                              "attribute_category", "last_update_date")]
        mc.frame(source, "compiler",
                 f"  party {row['party_id']}  [{row['attribute_category']}]  "
                 + "  ·  ".join(named),
                 producer="beam", tool="ParDo")

    # -- STEP 5 - the catalogue that made it possible --------------------
    _step(mc, source, 5, "FND_TABLES + FND_COLUMNS  ·  the application catalogue",
          "the warehouse schema is derived from the source's own metadata, not guessed")
    catalog_sql = ("SELECT c.application_short_name, c.table_name, c.column_name, c.data_type\n"
                   "FROM fnd_columns c ORDER BY c.column_name LIMIT 20")
    mc.frame(source, "compiler", f"$ {catalog_sql}",
             stream="command", producer="oracle-ebs-19c", tool="psql")
    _table(mc, source, "compiler", ["app", "table", "column", "type"],
           psql(cartridge, catalog_sql)[1:], [6, 16, 20, 10], "oracle-ebs-19c", "psql")
    mc.frame(source, "compiler",
             f"generic columns considered: {', '.join(c.upper() for c in GENERIC_COLUMNS)}",
             stream="system", producer="beam", tool="policy")

    return _finish(mc, source, cartridge, table, accepted, rejected, len(party_rows),
                   beam.__version__,
                   lambda reject: (f"party_id {reject['partyId']:<8} "
                                   f"{reject['attributeCategory']}  {reject['reason']}"))


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
    from scripts.mission_control_pipeline import CARTRIDGES as PIPE

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
        # Every cartridge now compiles from its own emulator, so there is no
        # generated stand-in to fall back to. Landing without a compile would
        # write rows the source lane never showed.
        raise StageError("compile_before_landing")
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
# ---------------------------------------------------------------------------
# Rate limiting
#
# The hosted lab is open to anyone, and four of the stages spend real money:
# land runs a BigQuery load job, embed calls Vertex through the warehouse, and
# search and bq each run a query. A per-IP bucket alone would not protect that,
# because the only client address available behind the proxy comes from
# X-Forwarded-For, which the caller controls. So the budget is defended by a
# global cap that no caller can opt out of, and the per-IP bucket exists only to
# keep one visitor from crowding out the others.
# ---------------------------------------------------------------------------

BILLABLE_STAGES = frozenset({"land", "embed", "search", "bq"})

_RATE_WINDOW_SECONDS = 60.0
_RATE_PER_IP = int(os.environ.get("KERAUN_RATE_PER_IP", "20"))
_RATE_GLOBAL = int(os.environ.get("KERAUN_RATE_GLOBAL", "60"))
_BILLABLE_DAILY_CAP = int(os.environ.get("KERAUN_BILLABLE_DAILY_CAP", "150"))


class RateLimiter:
    """Sliding-window counters guarding throughput and daily spend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._per_ip: dict[str, list[float]] = {}
        self._global: list[float] = []
        self._billable: list[float] = []

    @staticmethod
    def _prune(stamps: list[float], now: float, window: float) -> None:
        cutoff = now - window
        while stamps and stamps[0] < cutoff:
            stamps.pop(0)

    def check(self, client: str, stage: str) -> str | None:
        """Return a refusal code, or None when the call may proceed."""
        now = time.monotonic()
        with self._lock:
            # The daily cap is the one that protects the bill, so it is checked
            # first and is never bypassed.
            if stage in BILLABLE_STAGES:
                self._prune(self._billable, now, 86400.0)
                if len(self._billable) >= _BILLABLE_DAILY_CAP:
                    return "billable_daily_cap"

            self._prune(self._global, now, _RATE_WINDOW_SECONDS)
            if len(self._global) >= _RATE_GLOBAL:
                return "rate_limited_global"

            stamps = self._per_ip.setdefault(client, [])
            self._prune(stamps, now, _RATE_WINDOW_SECONDS)
            if len(stamps) >= _RATE_PER_IP:
                return "rate_limited"

            stamps.append(now)
            self._global.append(now)
            if stage in BILLABLE_STAGES:
                self._billable.append(now)

            # Keep the per-IP table from growing without bound.
            if len(self._per_ip) > 4096:
                for key in [k for k, v in self._per_ip.items() if not v]:
                    del self._per_ip[key]
        return None


LIMITER = RateLimiter()


def handler_for(token: str, project: str, dataset: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def authorized(self) -> bool:
            return hmac.compare_digest(
                self.headers.get("Authorization", ""), f"Bearer {token}")

        def client_id(self) -> str:
            """Best-effort caller identity for the courtesy per-IP bucket.

            X-Forwarded-For is supplied by the caller, so this is not a
            security boundary; the global cap is what actually holds.
            """
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()[:64]
            return self.client_address[0]

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
            refusal = LIMITER.check(self.client_id(), stage)
            if refusal is not None:
                self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"code": refusal})
                return
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
    exposure = "loopback only" if HOST in ("127.0.0.1", "localhost") else "REACHABLE OFF-BOX"
    print(f"Keraun stage executor listening on http://{HOST}:{PORT}  ({exposure})", flush=True)
    print(f"  limits: {_RATE_PER_IP}/min per caller, {_RATE_GLOBAL}/min overall, "
          f"{_BILLABLE_DAILY_CAP}/day for land, embed, search and bq", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
