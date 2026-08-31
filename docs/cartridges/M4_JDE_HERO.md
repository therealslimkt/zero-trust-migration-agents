# Milestone 4 JD Edwards hero cartridge

## Readiness and scope

The JDE hero is a deterministic, local `synthetic_fixture` packet. It demonstrates a bounded F0911 journal transformation using invented companies, document numbers, accounts, amounts, and descriptions. It does not connect to a JDE instance, execute Dataflow, write BigQuery, or establish production readiness.

The packet exposes the shared `CartridgePacket` contract with exactly eight JSON artifacts: `manifest`, `metadata`, `snapshot`, `delta`, `invalid`, `bronze`, `silver`, and `reconciliation`. The manifest binds the seven non-self-referential artifacts by canonical SHA-256 digest. The packet digest additionally binds the complete artifact map and packet identity.

## UPMJ date rule

JDE UPMJ dates use numeric `CYYDDD`:

- `C` is the century offset from 1900.
- `YY` is the two-digit year within that century.
- `DDD` is the one-based day of year.
- numeric zero represents a blank date and decodes to `None`.
- decoded fixture dates are bounded to 1900 through 2199.

Leading zeroes are absent in numeric storage, so `1` means 1900 day 1. Calendar validation is strict: `100366` is valid because 2000 is a leap year, while `101366`, day zero, day 367, negative values, booleans, strings, and out-of-range centuries are rejected. The encoder and decoder round-trip valid dates across all supported centuries.

## Deterministic journal semantics

The row identity is the ordered tuple of document company, document type, document number, line number, and ledger type. A delta is an immutable ordered journal with contiguous sequence numbers beginning at one. Operations are closed to `INSERT`, `UPDATE`, and `DELETE`:

- insert requires an absent key and a row whose key exactly matches the journal key;
- update requires an existing key and the same exact key binding;
- delete requires an existing key and no replacement row.

Application validates and operates on a private copy. A malformed later entry produces one safe typed error without mutating the supplied snapshot or delta. Final rows are sorted by the full key, making output independent of dictionary iteration order.

The bronze artifact is the append-only snapshot-plus-journal projection. Silver contains current rows after the update, delete, and insert, with UPMJ decoded to ISO dates. Reconciliation binds snapshot, journal, bronze, and silver digests and records exact input, operation, and output counts. Loader validation recomputes both projections and all reconciliation evidence before constructing the packet.

## Repeatability check

Run the focused suite with a supported Python version:

```sh
python -m pytest -q tests/edge_runtime/test_jde_adapter.py tests/cartridges/test_jde_packet.py
```

The packet tests load and digest the fixture in two independent pairs. Equality across both pairs is the local repeatability gate. Any artifact edit requires regenerating the expected reconciliation evidence and manifest digests; otherwise loading fails closed.
