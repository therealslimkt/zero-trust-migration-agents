# Milestone 4 Oracle EBS / Oracle 19c fixture cartridge

Status: **synthetic fixture readiness only**

## Delivered behavior

This cartridge demonstrates the Oracle E-Business Suite challenge that a
descriptive flexfield segment has no safe meaning without its FND metadata
context. The fixture compiler resolves every segment through the complete key:

```text
(application, table, context, segment, metadataVersion)
```

For example, `AR.HZ_PARTIES.ATTRIBUTE1` becomes `customerTier` under
`CUSTOMER_EXT`, but becomes `paymentProfile` under `SUPPLIER_EXT`. The
implementation never guesses from `ATTRIBUTE1` alone. A missing context,
duplicate full metadata key, unknown segment, invalid value, or stale metadata
version stops the packet with a stable failure code.

The packet includes the exact shared artifact set:

- `manifest`: Oracle 19c identity, synthetic readiness, watermark, and closed
  transformation description;
- `metadata`: synthetic FND definitions keyed by all five required dimensions;
- `snapshot`: three synthetic `HZ_PARTIES` source rows;
- `delta`: two `LAST_UPDATE_DATE` upserts and one explicit delete tombstone;
- `invalid`: missing-context, ambiguous-context, and metadata-version failures;
- `bronze`: deterministic final source-shaped state after applying the delta;
- `silver`: context-resolved fields with stable source keys;
- `reconciliation`: counts, deleted key, input/metadata/bronze/silver/transform digests,
  and a lineage digest binding the entire local transformation.

## Concrete result

The snapshot starts with parties `1001`, `1002`, and `1003`. The delta upgrades
customer `1001`, inserts supplier `1004`, and explicitly deletes supplier
`1002`. Reconciliation therefore proves three snapshot records, two upserts,
one delete, and three final records. `1001` resolves to a `PLATINUM` customer in
region `NA`; `1004` resolves to supplier payment profile `NET45`.

Two independent builds from identical fixture bytes must produce identical
packet and reconciliation digests. The reconciliation artifact separately
binds the input, actual FND metadata, expected bronze, expected silver, and transform-spec digests;
any modified expected artifact fails closed rather than silently regenerating
new "expected" evidence.

The verified local UI projection is:

```json
{
  "cartridgeId": "oracle_ebs_19c",
  "displayName": "Oracle EBS on Oracle 19c",
  "invalidRecords": 3,
  "packetDigest": "sha256:ecebcff7bc1414753460bc3e8da17c215d76617372a9d2206ae34db777b985b4",
  "readiness": "synthetic_fixture",
  "reconciliationDigest": "sha256:ff9ce11d9afdbf9e3d17636fe296ed4892da3bf131dfa8d07753c7a0a858f1a4",
  "silverRecords": 3,
  "snapshotRecords": 3,
  "sourceSystem": "oracle_ebs_19c",
  "transformSpecDigest": "sha256:d579858dce034f9090a7485d10b46c40fc974a9604c33566417bf607d1c4dffc"
}
```

These identifiers prove only the checked-in synthetic packet. They are not
cloud artifact IDs or production evidence.

## Agentic pattern and safety boundary

The cartridge uses a fixed deterministic fixture-compilation pattern:

```text
load exact artifacts -> validate metadata -> prove invalid cases
-> apply timestamp delta/delete -> resolve flexfields
-> compare expected bronze/silver -> reconcile digests -> emit packet
```

Every node is a function node and the model-call budget is zero. The bounded
build-time Oracle specialist lane owns only this module, its fixtures, focused
tests, and this document. Claude Opus 5 was requested as the primary design
assistant, but the managed environment rejected external repository transfer;
the lane therefore used local implementation and must receive an approved
Opus review after integration before claiming provider review completion.

All fixture values are invented and non-sensitive. Error messages contain
codes, not source values. The packet imports the shared immutable
`CartridgePacket` boundary and reports readiness exactly as
`synthetic_fixture`.

## Implemented versus deferred

Implemented here:

- deterministic local Oracle EBS/19c fixture compilation;
- full five-part FND flexfield lookup;
- strict global-watermark and per-key-monotonic `LAST_UPDATE_DATE` semantics;
- explicit delete reconciliation;
- expected bronze/silver comparison and repeatable digest evidence;
- adversarial fixture tests for context, metadata version, delta, delete, and
  reconciliation tampering.

Not implemented or claimed here:

- an Oracle JDBC or database connection;
- extraction from a real Oracle EBS instance or FND dictionary;
- credential handling, private connectivity, IAM, or Cloud SQL;
- a Dataflow Flex Template build or job execution;
- BigQuery datasets, tables, rows, queries, or reconciliation;
- production scale, performance, schema coverage, or deployment readiness.

Those are later integration/cloud-proof gates. The fixture must never be
presented as evidence that Oracle, Dataflow, or BigQuery ran.

## Important files and focused verification

- `cartridge_lab/oracle_ebs.py`
- `cartridge_lab/fixtures/oracle_ebs/*.json`
- `tests/cartridges/test_oracle_ebs_packet.py`

Focused verification:

```bash
python -m pytest -q tests/cartridges/test_oracle_ebs_packet.py
git diff --check
```
