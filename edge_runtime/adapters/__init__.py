"""Strict, source-specific legacy binary adapters.

Every adapter exposes ``decode(payload: SourcePayload) -> DecodedSource`` and
must reject malformed input rather than returning a partial record set.
"""
