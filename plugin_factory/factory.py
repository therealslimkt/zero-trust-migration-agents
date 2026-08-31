"""Narrow offline validator and deterministic evidence builder.

This module supports the repository's inert skills-only reference package. It
never starts an MCP server, executes package content, expands an archive, or
contacts a network service.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path, PurePosixPath
from typing import Any


PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
MAX_FILES = 256
MAX_FILE_BYTES = 1 << 20
MAX_TOTAL_BYTES = 8 << 20
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
_MANIFEST_FIELDS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}


class FactoryError(ValueError):
    """Safe, stable failure from package validation or verification."""


@dataclasses.dataclass(frozen=True, slots=True)
class InventoryEntry:
    path: str
    size: int
    sha256: str


@dataclasses.dataclass(frozen=True, slots=True)
class PluginReport:
    name: str
    version: str
    skills: tuple[str, ...]
    mcp_valid: bool
    diagnostics: tuple[str, ...]
    tree_digest: str


@dataclasses.dataclass(frozen=True, slots=True)
class VerificationReceipt:
    plugin_name: str
    plugin_version: str
    release_digest: str
    plugin_tree_digest: str
    sbom_digest: str
    provenance_digest: str
    status: str = "verified_inert"
    activation: str = "disabled"


def _fail(code: str) -> None:
    raise FactoryError(code)


def _reject_constant(_value: str) -> None:
    _fail("json_noncanonical")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("json_duplicate_key")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except FactoryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FactoryError("json_load") from exc


def _canonical(value: object) -> bytes:
    def validate(item: object) -> None:
        if item is None or type(item) in (bool, str):
            return
        if type(item) is int and -(1 << 63) <= item <= (1 << 63) - 1:
            return
        if type(item) is list:
            for child in item:
                validate(child)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _fail("json_noncanonical")
                validate(child)
            return
        _fail("json_noncanonical")

    validate(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 << 10), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_relative(path: str) -> bool:
    if not _SAFE_PATH.fullmatch(path) or "\\" in path:
        return False
    value = PurePosixPath(path)
    return not value.is_absolute() and all(part not in ("", ".", "..") for part in value.parts)


def _inventory(root: Path) -> tuple[InventoryEntry, ...]:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise FactoryError("package_root") from exc
    if not resolved_root.is_dir() or root.is_symlink():
        _fail("package_root")

    entries: list[InventoryEntry] = []
    total = 0
    folded: set[str] = set()
    for directory, names, files in os.walk(resolved_root, followlinks=False):
        names.sort()
        files.sort()
        for name in names:
            candidate = Path(directory) / name
            if candidate.is_symlink() or not candidate.is_dir():
                _fail("package_path_kind")
        for name in files:
            candidate = Path(directory) / name
            try:
                info = candidate.lstat()
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise FactoryError("package_path") from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                _fail("package_path_kind")
            try:
                relative = resolved.relative_to(resolved_root).as_posix()
            except ValueError:
                _fail("package_path_escape")
            if not _safe_relative(relative):
                _fail("package_path")
            folded_path = relative.casefold()
            if folded_path in folded:
                _fail("package_path_collision")
            folded.add(folded_path)
            if info.st_size > MAX_FILE_BYTES:
                _fail("package_file_size")
            total += info.st_size
            if total > MAX_TOTAL_BYTES:
                _fail("package_total_size")
            entries.append(
                InventoryEntry(relative, info.st_size, _file_sha256(candidate))
            )
            if len(entries) > MAX_FILES:
                _fail("package_file_count")
    return tuple(sorted(entries, key=lambda item: item.path))


def _tree_digest(entries: tuple[InventoryEntry, ...]) -> str:
    return _sha256(_canonical([dataclasses.asdict(entry) for entry in entries]))


def _skill_frontmatter(path: Path, directory_name: str) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise FactoryError("skill_load") from exc
    if len(lines) < 4 or lines[0] != "---":
        _fail("skill_frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError:
        _fail("skill_frontmatter")
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if not separator or key.strip() in fields:
            _fail("skill_frontmatter")
        fields[key.strip()] = value.strip()
    if set(fields) != {"name", "description"}:
        _fail("skill_frontmatter")
    if fields["name"] != directory_name or not _SKILL_NAME.fullmatch(fields["name"]):
        _fail("skill_name")
    if not fields["description"] or len(fields["description"]) > 1024:
        _fail("skill_description")


def validate_plugin(root: str | Path) -> PluginReport:
    """Validate the inert skills-only reference profile without execution."""

    plugin_root = Path(root)
    entries = _inventory(plugin_root)
    manifest_path = plugin_root / "plugin.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        _fail("manifest_missing")
    manifest = _load_json(manifest_path)
    if type(manifest) is not dict:
        _fail("manifest_shape")
    if manifest.get("$schema") != PLUGIN_SCHEMA:
        _fail("manifest_schema")
    name = manifest.get("name")
    if (
        type(name) is not str
        or not _NAME.fullmatch(name)
        or "--" in name
        or ".." in name
    ):
        _fail("manifest_name")
    diagnostics = [
        f"manifest_unknown_field:{field}"
        for field in sorted(set(manifest) - _MANIFEST_FIELDS)
    ]
    version = manifest.get("version", "0.0.0")
    if type(version) is not str or not version:
        _fail("manifest_version")
    for field in ("description", "homepage", "repository", "license"):
        if field in manifest and type(manifest[field]) is not str:
            _fail("manifest_metadata")
    if "keywords" in manifest and (
        type(manifest["keywords"]) is not list
        or any(type(value) is not str for value in manifest["keywords"])
    ):
        _fail("manifest_metadata")
    if "author" in manifest and type(manifest["author"]) is not dict:
        _fail("manifest_metadata")
    if "extensions" in manifest and type(manifest["extensions"]) is not dict:
        diagnostics.append("manifest_extensions_ignored")

    skills: list[str] = []
    skills_root = plugin_root / "skills"
    if skills_root.exists():
        if skills_root.is_symlink() or not skills_root.is_dir():
            _fail("skills_location")
        for child in sorted(skills_root.iterdir(), key=lambda item: item.name):
            if child.is_symlink() or not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.exists():
                continue
            if skill_file.is_symlink() or not skill_file.is_file():
                _fail("skill_path")
            _skill_frontmatter(skill_file, child.name)
            skills.append(child.name)

    mcp_valid = True
    mcp_path = plugin_root / "mcp.json"
    if mcp_path.exists():
        if mcp_path.is_symlink() or not mcp_path.is_file():
            _fail("mcp_location")
        mcp = _load_json(mcp_path)
        if type(mcp) is not dict or set(mcp) != {"$schema", "mcpServers"}:
            _fail("mcp_shape")
        if mcp["$schema"] != MCP_SCHEMA or type(mcp["mcpServers"]) is not dict:
            _fail("mcp_schema")
        if mcp["mcpServers"]:
            diagnostics.append("mcp_entries_not_verified")
            mcp_valid = False

    if not skills:
        _fail("reference_skill_missing")
    return PluginReport(
        name=name,
        version=version,
        skills=tuple(skills),
        mcp_valid=mcp_valid,
        diagnostics=tuple(diagnostics),
        tree_digest=_tree_digest(entries),
    )


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical(value) + b"\n")


def build_release(source: str | Path, destination: str | Path) -> str:
    """Build one deterministic, disabled release directory and return its digest."""

    source_root = Path(source)
    report = validate_plugin(source_root)
    output = Path(destination)
    if output.exists():
        _fail("release_exists")
    output.mkdir(parents=True)
    plugin_root = output / "plugin"
    shutil.copytree(source_root, plugin_root)
    inventory = _inventory(plugin_root)
    if _tree_digest(inventory) != report.tree_digest:
        _fail("release_copy_mismatch")
    evidence = output / "evidence"
    evidence.mkdir()

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": report.name,
                "version": report.version,
                "bom-ref": f"plugin:{report.name}@{report.version}",
                "hashes": [{"alg": "SHA-256", "content": report.tree_digest[7:]}],
            }
        },
        "components": [
            {
                "type": "file",
                "name": entry.path,
                "bom-ref": f"file:{entry.path}",
                "hashes": [{"alg": "SHA-256", "content": entry.sha256[7:]}],
            }
            for entry in inventory
        ],
    }
    sbom_path = evidence / "sbom.cdx.json"
    _write_json(sbom_path, sbom)

    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"name": f"plugin/{report.name}", "digest": {"sha256": report.tree_digest[7:]}}
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "urn:all-things-agentic:plugin-factory:v1",
                "externalParameters": {
                    "pluginSchema": PLUGIN_SCHEMA,
                    "profile": "inert-skills-only",
                },
                "internalParameters": {},
                "resolvedDependencies": [],
            },
            "runDetails": {
                "builder": {"id": "urn:all-things-agentic:local-plugin-factory"},
                "metadata": {"invocationId": f"urn:{report.tree_digest}"},
            },
        },
    }
    provenance_path = evidence / "provenance.intoto.json"
    _write_json(provenance_path, provenance)

    bundle = {
        "schemaVersion": "plugin-factory.bundle/v1",
        "pluginName": report.name,
        "pluginVersion": report.version,
        "pluginSchema": PLUGIN_SCHEMA,
        "profile": "inert-skills-only",
        "activation": "disabled",
        "pluginTreeDigest": report.tree_digest,
        "inventory": [dataclasses.asdict(entry) for entry in inventory],
        "sbomDigest": _file_sha256(sbom_path),
        "provenanceDigest": _file_sha256(provenance_path),
    }
    _write_json(output / "bundle.json", bundle)

    release_files = _inventory(output)
    checksum_entries = [entry for entry in release_files if entry.path != "SHA256SUMS"]
    checksum_body = "".join(
        f"{entry.sha256[7:]}  {entry.path}\n" for entry in checksum_entries
    ).encode("ascii")
    (output / "SHA256SUMS").write_bytes(checksum_body)
    return _sha256(checksum_body)


def verify_release(root: str | Path, expected_release_digest: str) -> VerificationReceipt:
    """Verify a release as inert bytes; never install or activate it."""

    if type(expected_release_digest) is not str or not _DIGEST.fullmatch(expected_release_digest):
        _fail("expected_digest")
    release = Path(root)
    all_entries = _inventory(release)
    checksums_path = release / "SHA256SUMS"
    if checksums_path.is_symlink() or not checksums_path.is_file():
        _fail("checksums_missing")
    if _file_sha256(checksums_path) != expected_release_digest:
        _fail("release_digest_mismatch")
    try:
        lines = checksums_path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise FactoryError("checksums_load") from exc
    expected: dict[str, str] = {}
    for line in lines:
        digest, separator, relative = line.partition("  ")
        if (
            separator != "  "
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not _safe_relative(relative)
            or relative == "SHA256SUMS"
            or relative in expected
        ):
            _fail("checksums_shape")
        expected[relative] = "sha256:" + digest
    if list(expected) != sorted(expected):
        _fail("checksums_order")
    actual = {entry.path: entry.sha256 for entry in all_entries if entry.path != "SHA256SUMS"}
    if expected != actual:
        _fail("checksums_mismatch")

    bundle = _load_json(release / "bundle.json")
    required = {
        "schemaVersion",
        "pluginName",
        "pluginVersion",
        "pluginSchema",
        "profile",
        "activation",
        "pluginTreeDigest",
        "inventory",
        "sbomDigest",
        "provenanceDigest",
    }
    if type(bundle) is not dict or set(bundle) != required:
        _fail("bundle_shape")
    if (
        bundle["schemaVersion"] != "plugin-factory.bundle/v1"
        or bundle["pluginSchema"] != PLUGIN_SCHEMA
        or bundle["profile"] != "inert-skills-only"
        or bundle["activation"] != "disabled"
    ):
        _fail("bundle_identity")
    report = validate_plugin(release / "plugin")
    inventory = _inventory(release / "plugin")
    if (
        bundle["pluginName"] != report.name
        or bundle["pluginVersion"] != report.version
        or bundle["pluginTreeDigest"] != report.tree_digest
        or bundle["inventory"] != [dataclasses.asdict(entry) for entry in inventory]
        or bundle["sbomDigest"] != _file_sha256(release / "evidence" / "sbom.cdx.json")
        or bundle["provenanceDigest"]
        != _file_sha256(release / "evidence" / "provenance.intoto.json")
    ):
        _fail("bundle_mismatch")
    return VerificationReceipt(
        plugin_name=report.name,
        plugin_version=report.version,
        release_digest=expected_release_digest,
        plugin_tree_digest=report.tree_digest,
        sbom_digest=bundle["sbomDigest"],
        provenance_digest=bundle["provenanceDigest"],
    )
