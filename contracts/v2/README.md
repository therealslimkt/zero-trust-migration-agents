# v2 enterprise fleet contracts

This directory is the additive, provider-neutral wire contract for the ADK 2 product runtime. It does not change the existing `contracts/` or `contracts/web/v1/` surfaces. `schemaVersion` is fixed at `2.0.0`; `workflowVersion` and cartridge versions evolve independently as semantic versions.

## Public boundary

`openapi.json` exposes exactly three bearer-authenticated orchestration routes:

- `GET /api/v2/runs/{run_id}/orchestration`
- `GET /api/v2/runs/{run_id}/events`
- `POST /api/v2/runs/{run_id}/inputs/{interrupt_id}`

The input route accepts only clarification and task input. Simulation and production approval remain on their existing authenticated control-plane endpoints. A resume message wakes a node but is never approval evidence.

All JSON objects are closed. Events and artifacts carry content-addressed references rather than raw rows, credentials, proprietary binaries, prompts, or private reasoning. Vale, Flow, Ledger, and Forge are deterministic component IDs and cannot appear as model-agent IDs. Cartridge capability claims keep runtime readiness, input fidelity, and plugin distribution status separate.

## Integrity and fixtures

Canonical JSON uses UTF-8, sorted object keys, no insignificant whitespace, and no non-finite numbers. The manifest digest is SHA-256 over a canonical `{relative_path: canonical_document_digest}` map for every listed OpenAPI, schema, and example document. A cartridge digest is SHA-256 over its canonical object with `cartridgeDigest` omitted.

Negative fixtures are closed mutation descriptors: each changes exactly one field in a named valid example. This makes the rejection cause reviewable and avoids maintaining stale duplicate documents.

Run the offline suite from the repository root:

```text
python3 -m unittest discover -s contracts/v2/tests -p 'test_*.py'
python3 contracts/v2/tools/verify_contracts.py
```

The test helper implements only the Draft 2020-12 keywords used by this repository. Production services must use a complete Draft 2020-12 validator and enforce cross-record facts—current checkpoint, tenant authorization, expiry, idempotency, and approval authority—against Cloud SQL.
