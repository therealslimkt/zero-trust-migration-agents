# Migration Contracts 1.0.0

The files under `contracts/` are the language-neutral trust boundary for one
portfolio migration containing exactly three sources: JDE/AS400, SAP MaxDB,
and Accpac/Btrieve. JSON Schema draft 2020-12 is canonical. `openapi.json`
defines the REST and server-sent event surface without redefining the domain
objects.

## Source identity and network boundary

| Source ID | Tailscale MagicDNS hostname | BigQuery target |
| --- | --- | --- |
| `jde` | `legacy-jde-db` | `jde_f0101` |
| `maxdb` | `legacy-maxdb` | `sap_kna1` |
| `btrieve` | `legacy-btrieve-db` | `accpac_arcus` |

Public contracts use the stable MagicDNS names. IP addresses are neither
accepted nor emitted. The create request requires each source exactly once.

## State and approval model

A run advances through `created`, `inventorying`, `redacting`, `planning`,
`awaiting_approval`, `approved`, `executing`, `verifying`, and `completed`.
`failed` and `cancelled` are terminal alternatives. Individual source progress
uses the same vocabulary so a partial failure remains visible without
inventing a second state machine.

Approval is one portfolio-level decision. The client must submit the
`portfolioPlanDigest` returned by the run. The service must reject a stale or
unknown digest rather than approving a mutable plan. An approval permits only
the trusted pipeline to interpret the three validated `TransformPlan`
documents.

## Declarative transformation boundary

`TransformPlan` accepts only the closed set of typed operations declared in
its schema: text decoding, packed-decimal conversion, date mapping, rename,
cast, drop, and deterministic HMAC tokenization. Every operation is a closed
object. Code, scripts, commands, expression strings, and undeclared operation
parameters fail validation and must never reach an executor.

Raw records and raw PII are not part of these contracts. Evidence references
contain stable artifact identifiers, categories, and SHA-256 digests, not
payloads. Tokenization refers to an edge-held key by opaque `secret://`
reference; the key value does not cross the boundary.

## SSE wire format

`GET /api/v1/migrations/{run_id}/events` returns `text/event-stream`. Each SSE
message uses its event ID in the SSE `id` field and encodes one
`sse-event.schema.json` document in `data`. Source-scoped event types require a
`sourceId`; portfolio events forbid one. Clients reconnect with the
`Last-Event-ID` header, and servers resume strictly after that event.

## Deterministic validation

From the repository root, run:

```bash
python3 -m unittest discover -s tests/contracts -v
```

The suite uses only the Python standard library. It parses every schema,
resolves every local reference, validates positive examples for all three
sources, validates the OpenAPI surface, and proves that IP hostnames, raw PII,
and executable-content properties are rejected. Production implementations
should use a complete draft 2020-12 validator; the pinned development
dependency is recorded in `requirements-dev.txt`.
