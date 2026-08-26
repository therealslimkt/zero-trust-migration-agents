#!/usr/bin/env python3
"""Verify all three live sources without printing or persisting record values."""

from __future__ import annotations

import argparse
import json
import os

from edge_runtime.adapters import btrieve, jde, maxdb
from edge_runtime.transport import TailscaleSSHTransport
from edge_runtime.types import SOURCE_SPECS
from edge_security.local_gemma_agent import TailscaleGemmaReviewer
from edge_security.pii_redactor import DeterministicRedactor


DECODERS = {
    "jde": jde.decode,
    "maxdb": maxdb.decode,
    "btrieve": btrieve.decode,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify private reads, strict decoding, and edge-local redaction"
    )
    parser.add_argument("--tailscale-binary", default="tailscale")
    parser.add_argument("--token-key-env", default="ZTM_EDGE_TOKEN_KEY")
    args = parser.parse_args()

    token_key = os.environ.get(args.token_key_env)
    if token_key is None:
        parser.error(f"{args.token_key_env} must contain an edge tokenization key")

    transport = TailscaleSSHTransport(tailscale_binary=args.tailscale_binary)
    redactor = DeterministicRedactor(token_key.encode("utf-8"))
    gemma = TailscaleGemmaReviewer(tailscale_binary=args.tailscale_binary)
    summaries = []

    for source_id in ("jde", "maxdb", "btrieve"):
        payload = transport.read(SOURCE_SPECS[source_id])
        decoded = DECODERS[source_id](payload)
        deterministic = redactor.sanitize(decoded)
        review = gemma.review(deterministic.sanitized)
        if review.status != "passed" or review.finding_count:
            raise RuntimeError(
                f"edge-local residual-PII review blocked source: {source_id}"
            )
        summaries.append(
            {
                "sourceId": source_id,
                "hostname": payload.spec.hostname,
                "byteCount": payload.size_bytes,
                "sourceDigest": "sha256:" + payload.sha256,
                "recordCount": len(decoded.records),
                "deterministicFindingCount": deterministic.finding_count,
                "deterministicEvidenceDigest": deterministic.evidence_digest,
                "localGemmaModel": review.model,
                "localGemmaExecutionLocation": review.execution_location,
                "localGemmaStatus": review.status,
                "localGemmaFindingCount": review.finding_count,
                "localGemmaEvidenceDigest": review.evidence_digest,
            }
        )

    print(
        json.dumps(
            {"status": "passed", "sourceCount": len(summaries), "sources": summaries},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
