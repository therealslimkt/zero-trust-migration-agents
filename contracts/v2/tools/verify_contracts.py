#!/usr/bin/env python3
"""Deterministic integrity helpers for the additive v2 contract package."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


V2_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = V2_ROOT / "manifest.json"


class IntegrityError(ValueError):
    """Raised when a contract path or digest fails closed."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_bytes(document: Any) -> bytes:
    """RFC 8785-compatible for this package's integer/string-only JSON subset."""
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(document: Any, omit_top_level: str | None = None) -> str:
    value = copy.deepcopy(document)
    if omit_top_level is not None:
        if not isinstance(value, dict) or omit_top_level not in value:
            raise IntegrityError(f"missing digest field {omit_top_level}")
        del value[omit_top_level]
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def resolve_local(relative_path: str) -> Path:
    candidate = (V2_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(V2_ROOT.resolve())
    except ValueError as error:
        raise IntegrityError(f"path escapes contracts/v2: {relative_path}") from error
    if not candidate.is_file():
        raise IntegrityError(f"missing contract file: {relative_path}")
    return candidate


def listed_files(manifest: dict[str, Any]) -> list[str]:
    paths = [manifest["openapi"], *manifest["schemas"]]
    for group in ("valid", "invalid"):
        paths.extend(item["path"] for item in manifest["examples"][group])
    if len(paths) != len(set(paths)):
        raise IntegrityError("manifest contains duplicate paths")
    return sorted(paths)


def contract_set_digest(manifest: dict[str, Any]) -> str:
    file_digests = {
        path: canonical_digest(load_json(resolve_local(path)))
        for path in listed_files(manifest)
    }
    return canonical_digest(file_digests)


def embedded_digest_matches(document: dict[str, Any], field: str) -> bool:
    recorded = document.get(field)
    return isinstance(recorded, str) and recorded == canonical_digest(document, field)


def apply_mutation(base: Any, mutation: dict[str, Any]) -> Any:
    if mutation.get("operation") != "set":
        raise IntegrityError("only deterministic set mutations are supported")
    result = copy.deepcopy(base)
    parts = mutation["path"].split("/")[1:]
    current = result
    for raw_part in parts[:-1]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        current = current[int(part)] if isinstance(current, list) else current[part]
    final = parts[-1].replace("~1", "/").replace("~0", "~")
    if isinstance(current, list):
        current[int(final)] = mutation["value"]
    else:
        current[final] = mutation["value"]
    return result


def verify_manifest(path: Path = MANIFEST) -> None:
    manifest = load_json(path)
    if manifest.get("contractVersion") != "2.0.0":
        raise IntegrityError("manifest contractVersion must be 2.0.0")
    expected = manifest.get("integrity", {}).get("contractSetDigest")
    actual = contract_set_digest(manifest)
    if expected != actual:
        raise IntegrityError(f"contract set digest mismatch: expected {expected}, got {actual}")

    for item in manifest["examples"]["valid"]:
        if item.get("embeddedDigestField"):
            document = load_json(resolve_local(item["path"]))
            if not embedded_digest_matches(document, item["embeddedDigestField"]):
                raise IntegrityError(f"embedded digest mismatch: {item['path']}")


def main() -> int:
    verify_manifest()
    print("contracts/v2 integrity verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
