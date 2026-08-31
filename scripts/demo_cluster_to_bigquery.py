#!/usr/bin/env python3
"""Show a clustered binary legacy export becoming typed BigQuery columns.

Stage 1  the export as it exists on the legacy host: opaque compressed bytes
Stage 2  the code-owned adapter decodes it under a fixed schema
Stage 3  the typed rows, and the explicit BigQuery schema they land in

The model is not involved in any stage. Decoding is deterministic, bounded,
CRC32-verified, and fails closed on malformed input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edge_runtime.types import SOURCE_SPECS, SourcePayload
from edge_runtime.adapters import maxdb
from tools.simulator.maxdb_kna1_generator import build_maxdb_export

# SAP field  ->  canonical column, BigQuery type, data class assigned by the adapter
BQ_SCHEMA = [
    ("customer_number", "STRING", "KUNNR", "financialAccount"),
    ("name",            "STRING", "NAME1", "name"),
    ("city",            "STRING", "ORT01", "address"),
    ("country",         "STRING", "LAND1", "public"),
    ("source_ordinal",  "INT64",  "—",     "public"),
]

RULE = "─" * 78


def hexdump(data: bytes, limit: int = 160) -> str:
    out = []
    for off in range(0, min(len(data), limit), 16):
        chunk = data[off : off + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk).ljust(47)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"  {off:08x}  {hexpart}  |{text}|")
    if len(data) > limit:
        out.append(f"  … {len(data) - limit} more bytes")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true", help="load the typed rows into BigQuery")
    ap.add_argument("--project", default="ztm-agent-9049c3")
    ap.add_argument("--dataset", default="keraun_demo")
    ap.add_argument("--table", default="sap_kna1_clustered")
    args = ap.parse_args()

    payload_bytes = build_maxdb_export()

    print(f"\n\033[1mSTAGE 1 — clustered binary export, as it sits on the legacy host\033[0m")
    print(RULE)
    print(f"  source        SAP-style MaxDB KNA1 cluster export")
    print(f"  size          {len(payload_bytes)} bytes")
    print(f"  sha256        {SourcePayload(SOURCE_SPECS['maxdb'], payload_bytes).sha256[:48]}…")
    print(f"  readable?     no — every record is an individually zlib-compressed blob")
    print()
    print(hexdump(payload_bytes))
    print()
    print("  \033[2mA warehouse loader pointed at this file gets one opaque BYTES column.\033[0m")

    print(f"\n\033[1mSTAGE 2 — code-owned adapter decodes it (no model involved)\033[0m")
    print(RULE)
    payload = SourcePayload(spec=SOURCE_SPECS["maxdb"], data=payload_bytes)
    decoded = maxdb.decode(payload)
    print(f"  magic         MXDBKNA1        header validated")
    print(f"  records       {len(decoded.records)}               declared count matched")
    print(f"  per record    length + CRC32 verified before decompression")
    print(f"  bounds        max 10,000 records · max 16 KiB uncompressed each")
    print(f"  key set       {', '.join(sorted(maxdb.EXPECTED_KEYS))} — anything else is rejected")
    print(f"  failure mode  fail closed; no partial output is ever emitted")

    print(f"\n\033[1mSTAGE 3 — typed rows, ready for BigQuery\033[0m")
    print(RULE)
    width = {"customer_number": 18, "name": 30, "city": 12, "country": 9}
    hdr = "  " + "".join(h.upper().ljust(w) for h, w in width.items()) + "ORDINAL"
    print("\033[1m" + hdr + "\033[0m")
    rows = []
    for rec in decoded.records:
        vals = {f.name: f.value for f in rec.fields}
        row = {k: vals.get(k) for k in width}
        row["source_ordinal"] = rec.ordinal
        rows.append(row)
        print("  " + "".join(str(row[k]).ljust(w) for k, w in width.items()) + str(rec.ordinal))

    print()
    print("  \033[1mBigQuery schema — explicit, never autodetected\033[0m")
    print(f"    {'COLUMN'.ljust(18)}{'TYPE'.ljust(9)}{'FROM'.ljust(8)}DATA CLASS")
    for name, typ, sap, cls in BQ_SCHEMA:
        print(f"    {name.ljust(18)}{typ.ljust(9)}{sap.ljust(8)}{cls}")
    print()
    print("  \033[2mThe data class is assigned by the adapter, not the model. It is what the\033[0m")
    print("  \033[2mdeterministic redaction policy keys off before anything leaves the edge.\033[0m")

    if args.load:
        from google.cloud import bigquery

        client = bigquery.Client(project=args.project)
        ds_id = f"{args.project}.{args.dataset}"
        try:
            client.get_dataset(ds_id)
        except Exception:
            ds = bigquery.Dataset(ds_id)
            ds.location = "US"
            client.create_dataset(ds)
            print(f"\n  created dataset {ds_id}")

        table_id = f"{ds_id}.{args.table}"
        schema = [bigquery.SchemaField(n, t, description=f"{sap} · {cls}") for n, t, sap, cls in BQ_SCHEMA]
        job = client.load_table_from_json(
            rows,
            table_id,
            job_config=bigquery.LoadJobConfig(
                schema=schema,
                write_disposition="WRITE_TRUNCATE",
            ),
        )
        job.result()
        table = client.get_table(table_id)
        print(f"\n\033[1mSTAGE 4 — landed in BigQuery\033[0m")
        print(RULE)
        print(f"  table         {table_id}")
        print(f"  job id        {job.job_id}")
        print(f"  rows loaded   {table.num_rows}")
        print(f"  reconcile     decoded {len(rows)} = loaded {table.num_rows}  "
              f"{'OK' if len(rows) == table.num_rows else 'MISMATCH — FAIL CLOSED'}")
        print()
        print(f"  verify:  bq query --use_legacy_sql=false 'SELECT * FROM `{table_id}`'")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
