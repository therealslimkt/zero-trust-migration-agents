# Milestone 4 Microsoft Dynamics AX fixture packet

Status: local synthetic fixture only

This cartridge supplies deterministic evidence for the `dynamics_ax` family.
It reads checked-in JSON and returns the shared `CartridgePacket` with
`readiness="synthetic_fixture"`. It contains no connector, credential,
customer label, deployment, or external-system mutation.

## Packet contents

The packet is loaded by `cartridge_lab/ax.py` from
`cartridge_lab/fixtures/ax/` and contains exactly the shared artifact set:

- `manifest.json`: fixture identity, transform digest, snapshot high
  watermark, and embedded digests for every other artifact.
- `metadata.json`: composite identity, ordered watermark, and synthetic
  base/derived table declarations.
- `snapshot.json`: six current-state rows across two companies.
- `delta.json`: one update, two inserts, and two ordered delete tombstones.
- `invalid.json`: an orphan derived row, duplicate composite identity, and
  cross-company inheritance link, each with its expected failure code.
- `bronze.json`: eleven append-only normalized event facts with record
  digests rather than copied payloads.
- `silver.json`: six deterministic current-state rows after delta merge.
- `reconciliation.json`: exact counts plus independent count and final-key
  digests.

All names and values use explicit synthetic labels such as `SYN01`,
`synthetic_partition_01`, and `SyntheticAxPartyBase`.

## AX-specific invariants

Row authority is the complete key:

```text
(company, partition, table, RecId)
```

`RecId` is never treated as globally unique. The fixture intentionally uses
`RecId=1001` in two companies and in both a base and derived table. Dropping
any key component would collapse distinct rows and is rejected.

`SyntheticAxCustomerDerived` declares that it extends
`SyntheticAxPartyBase`. Every derived row carries a `baseIdentity` with the
same company, partition, and `RecId`, and that base identity must be present in
the current row set. Cross-company links, wrong base tables, and missing base
rows fail closed.

The watermark is ordered by `(modifiedDateTime, RecId)` and uses
`strictly_after_last_committed` semantics. Delta sequence and watermark order
must both be contiguous. An upsert's record timestamp and identity must match
its watermark; a delete must contain no record body and must match a current
composite identity.

## Digest and reconciliation evidence

Digest checks are deliberately performed twice:

1. `manifest.json` embeds the canonical SHA-256 digest of each separate
   metadata, snapshot, delta, invalid, bronze, silver, and reconciliation
   file.
2. `load_ax_packet()` independently reads and recomputes every digest before
   constructing the shared packet. Tests separately repeat the recomputation
   and recompute the complete packet digest.

Reconciliation is closed and exact:

| Fact | Count |
| --- | ---: |
| Snapshot rows | 6 |
| Delta rows | 5 |
| Existing-identity updates | 1 |
| Inserted identities | 2 |
| Delete tombstones | 2 |
| Unmatched deletes | 0 |
| Bronze rows | 11 |
| Silver rows | 6 |

The two tombstones remove both the synthetic derived and base identities for
`SYN01` / `RecId=1002`. The final silver set is revalidated for inheritance
after the merge.

## Mission Control seam

The stable local UI summary is:

```json
{
  "cartridgeId": "dynamics_ax",
  "displayName": "Microsoft Dynamics AX",
  "sourceSystem": "microsoft_dynamics_ax",
  "readiness": "synthetic_fixture",
  "packetDigest": "sha256:5ce2bde2f9878e248cb8423d08512703779b28994aebb963f660246c53cfb826",
  "transformSpecDigest": "sha256:7f875b9bfc9fce91f311e2dd60c3172e45ac3a1860f47d979470621248111b80",
  "reconciliationDigest": "sha256:aceccb767cfab01c81d8f8b1c91b4fb70bf45e56c7455be7d55023ecb469b793",
  "snapshotRecords": 6,
  "silverRecords": 6,
  "invalidRecords": 3
}
```

This is an additive UI integration seam only. It does not claim a Dynamics AX
connection, Dataflow job, BigQuery table, or cloud deployment.

## Focused verification

```sh
python -m unittest -v tests.cartridges.test_ax_packet
```

The tests cover the shared packet shape, stable summary, composite identity,
inheritance, watermark/delta/delete merge, invalid cases, reconciliation, and
embedded-versus-recomputed digests.
