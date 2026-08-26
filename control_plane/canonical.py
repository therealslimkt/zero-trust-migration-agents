"""Canonical IDs and digests shared by artifact, planning, and approval code."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping


SCHEMA_VERSION = "1.0.0"
SOURCE_ORDER = ("jde", "maxdb", "btrieve")
TARGET_TABLES = {
    "jde": "jde_f0101",
    "maxdb": "sap_kna1",
    "btrieve": "accpac_arcus",
}

_RUN_ID = re.compile(r"^mig_[A-Za-z0-9]{12,64}$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def document_digest(
    document: Mapping[str, object], *, omit: Iterable[str] = ()
) -> str:
    omitted = frozenset(omit)
    canonical = {key: value for key, value in document.items() if key not in omitted}
    return sha256_digest(canonical_json_bytes(canonical))


def stable_id(prefix: str, *parts: str, length: int = 20) -> str:
    if not prefix or not prefix.endswith("_"):
        raise ValueError("ID prefix must be nonempty and end with underscore")
    if not 12 <= length <= 64:
        raise ValueError("ID digest length must be between 12 and 64")
    seed = canonical_json_bytes(list(parts))
    return prefix + hashlib.sha256(seed).hexdigest()[:length]


def require_run_id(run_id: str) -> str:
    if _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("run_id does not match the migration contract")
    return run_id


def require_digest(digest: str) -> str:
    if _DIGEST.fullmatch(digest) is None:
        raise ValueError("digest does not match the migration contract")
    return digest


def portfolio_plan_digest(plans: Iterable[Mapping[str, object]]) -> str:
    by_source = {}
    for plan in plans:
        source_id = plan.get("sourceId")
        digest = plan.get("planDigest")
        if source_id not in SOURCE_ORDER or source_id in by_source:
            raise ValueError("portfolio plans must contain each source exactly once")
        if not isinstance(digest, str):
            raise ValueError("every portfolio plan requires a digest")
        by_source[source_id] = require_digest(digest)
    if set(by_source) != set(SOURCE_ORDER):
        raise ValueError("portfolio plans must contain each source exactly once")
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "plans": [
            {"sourceId": source_id, "planDigest": by_source[source_id]}
            for source_id in SOURCE_ORDER
        ],
    }
    return sha256_digest(canonical_json_bytes(payload))
