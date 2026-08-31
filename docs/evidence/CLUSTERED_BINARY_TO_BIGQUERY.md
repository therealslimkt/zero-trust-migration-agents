# Evidence: clustered binary legacy data → typed BigQuery columns

Captured (UTC): `2026-08-31T22:31:03Z` · project `ztm-agent-9049c3`

The hardest legacy-ERP pathology in one run: a SAP-style MaxDB `KNA1` cluster export
where **every record is an individually zlib-compressed blob**, decoded by code-owned
adapters into explicitly typed BigQuery columns.

```bash
venv/bin/python scripts/demo_cluster_to_bigquery.py --load
```

## Stage 1 — the export as it sits on the legacy host

386 bytes. A warehouse loader pointed at this gets one opaque `BYTES` column.

```text
00000000  4d 58 44 42 4b 4e 41 31 01 01 04 00 58 00 00 00  |MXDBKNA1....X...|
00000010  52 00 00 00 d2 c7 dc f0 78 da ab 56 f2 0e f5 f3  |R.......x..V....|
00000020  0b 52 b2 52 32 80 01 43 25 1d 25 1f 47 3f 17 43  |.R.R2..C%.%.G?.C|
```

## Stage 2 — deterministic decode (no model involved)

`edge_runtime/adapters/maxdb.py` validates the `MXDBKNA1` magic and version, checks each
cluster's declared length **and CRC32 before decompressing**, enforces bounds (≤10,000
records, ≤16 KiB uncompressed each), and rejects any key outside
`{KUNNR, NAME1, ORT01, LAND1}`. Malformed input produces **no partial output**.

## Stage 3 — typed rows with an adapter-assigned data class

| BigQuery column | Type | From | Data class |
| --- | --- | --- | --- |
| `customer_number` | STRING | KUNNR | financialAccount |
| `name` | STRING | NAME1 | name |
| `city` | STRING | ORT01 | address |
| `country` | STRING | LAND1 | public |
| `source_ordinal` | INT64 | — | public |

The data class is assigned by the adapter, not the model, and is what the deterministic
redaction policy keys off before anything leaves the edge.

## Stage 4 — landed and reconciled in BigQuery

| Field | Value |
| --- | --- |
| Table | `ztm-agent-9049c3.keraun_demo.sap_kna1_clustered` |
| Load job ID | `ce235d05-810e-4457-b134-76dc9dfa4717` |
| Rows loaded | 4 |
| Reconciliation | decoded 4 = loaded 4 → **OK** |

Schema is declared explicitly; `--autodetect` is never used.

## Verify independently

```bash
bq query --use_legacy_sql=false \
  'SELECT * FROM `ztm-agent-9049c3.keraun_demo.sap_kna1_clustered` ORDER BY source_ordinal'
```

```text
+-----------------+------------------------------+---------+---------+----------------+
| customer_number |             name             |  city   | country | source_ordinal |
+-----------------+------------------------------+---------+---------+----------------+
| 0000000001      | Northstar Components LLC     | Chicago | US      |              0 |
| 0000000002      | Blue Heron Manufacturing Ltd | Toronto | CA      |              1 |
| 0000000003      | Juniper Industrial GmbH      | Berlin  | DE      |              2 |
| 0000000004      | Copper Finch Systems KK      | Tokyo   | JP      |              3 |
+-----------------+------------------------------+---------+---------+----------------+
```

Fixture data is synthetic and deidentified. The structure reproduces SAP cluster-table
packing; it is not a licensed SAP database.
