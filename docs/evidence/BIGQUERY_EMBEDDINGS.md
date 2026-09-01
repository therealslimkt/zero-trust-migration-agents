# Evidence: landed rows are embedded in BigQuery and searchable by meaning

The warehouse lane claims the migrated table is AI-ready. This is what makes
that true, and how to check it.

## What was built

| Object | Purpose |
| --- | --- |
| `ztm-agent-9049c3.us.keraun_vertex` | `CLOUD_RESOURCE` connection; its service account holds `roles/aiplatform.user` |
| `keraun_demo.embedder` | remote model over `text-embedding-005` |
| `keraun_demo.jde_f0101_embeddings` | 498 rows · 768 dimensions · 0 failures |

Embeddings are produced by `ML.GENERATE_EMBEDDING` **inside BigQuery**. Nothing
is exported to be embedded and no row values are sent anywhere by the
application; the connection is what reaches Vertex, not us.

## Reproduce

```sql
CREATE OR REPLACE MODEL `ztm-agent-9049c3.keraun_demo.embedder`
REMOTE WITH CONNECTION `ztm-agent-9049c3.us.keraun_vertex`
OPTIONS (ENDPOINT = 'text-embedding-005');
```

Then run the **Embed for AI** control in the warehouse lane, or:

```bash
curl -X POST localhost:4345/v1/stages/embed -d '{"cartridge":"jde"}'
```

## Why it is not keyword search

Ask in plain language and the nearest rows come back by meaning. The query
words do not appear in any row.

`"metal foundry and castings business in Australia"`

| address_number | alpha_name | tax_id | distance |
| --- | --- | --- | --- |
| 5 | Juniper Castings Pty | AU | 0.3094 |
| 93 | Cobalt Castings LLC | AU | 0.3286 |
| 286 | Beacon Hill Castings Pty | JP | 0.3397 |

`"shipping and freight company in the Netherlands"`

| address_number | alpha_name | tax_id | distance |
| --- | --- | --- | --- |
| 356 | Sandpiper Logistics SA | NL | 0.3281 |
| 87 | Meridian Logistics BV | NL | 0.3313 |

No row contains *foundry*, *shipping*, *freight* or *Netherlands*. The match is
semantic: foundry resolves to castings, and the Dutch firms rank above the
`BV`-suffixed companies registered elsewhere.

## Governance

`VECTOR_SEARCH` is a fixed, parameterised query in `scripts/stage_executor.py`.
The caller supplies one bound parameter and never composes SQL, so this surface
cannot be used to reach the rest of the warehouse.
