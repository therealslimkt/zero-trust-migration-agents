# Browser web contract v1

This directory is the source of truth for the browser-facing `/api/web/v1` BFF.
It is additive and does not modify or replace the internal service-token
`/api/v1` contract.

`DemoManifest` is a completed, immutable replay package. Its `bundleDigest` is
`sha256` over compact UTF-8 JSON with object keys sorted lexicographically,
array order preserved, and only the root `bundleDigest` member omitted. The Go
publisher validates this digest, the exact three-source set, completion and
reconciliation invariants, required evidence, reference integrity, ordered
events, and absence of credential material before publication.

Publication request bodies are capped at 8 MiB. The publisher does not trust a
manifest's classification or evidence digests: it requires a server-side owner
classification record and re-hashes every artifact body obtained from a
trusted artifact reader. Publication storage is create-only by `demoId` and
content address; an identical retry is idempotent, while a different digest for
an existing ID is rejected.

Public endpoints are read-only. Practice approval is intentionally client-local
and therefore has no HTTP operation. Every live mutation requires an Identity
Platform bearer token; the live approval request intentionally has no actor
field because the BFF derives that identity from verified claims. Live-run
creation likewise accepts no owner or requester field; ownership in every run
response is injected from the verified session by the BFF.
