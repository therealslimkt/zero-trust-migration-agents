# M4 local fixture packet contract

The midnight M4 slice is a local, synthetic-fixture proof for JDE, Microsoft
Dynamics AX, and Oracle EBS/Oracle 19c. It is deliberately separate from
frozen v1 APIs and from the Dataflow/BigQuery replay screens.

Each packet is JSON with these exact top-level fields:

```text
cartridge_id, display_name, source_system, readiness,
transform_spec_digest, artifacts
```

`readiness` is exactly `synthetic_fixture`. `artifacts` has exactly
`manifest`, `metadata`, `snapshot`, `delta`, `invalid`, `bronze`, `silver`,
and `reconciliation`. Packets are canonical-JSON digested twice in tests.

The additive lab view may show only packet and reconciliation digests, bounded
record counts, expected silver-output labels, and synthetic fixture metadata.
It must never claim a Dataflow job, BigQuery table, deployed plugin, hosted
backend, or customer data execution.
