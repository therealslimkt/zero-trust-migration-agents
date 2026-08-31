"""Closed local-fixture packet contract shared by the three M4 cartridges."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


REQUIRED_PACKET_ARTIFACTS = (
    "manifest",
    "metadata",
    "snapshot",
    "delta",
    "invalid",
    "bronze",
    "silver",
    "reconciliation",
)
_CARTRIDGE_ID = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class CartridgePacketError(ValueError):
    """A local fixture packet does not meet the closed M4 lab contract."""


def canonical_digest(value: object) -> str:
    """Return a stable digest for closed JSON-compatible fixture evidence."""

    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise CartridgePacketError("packet_noncanonical_value") from exc
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class CartridgePacket:
    """A complete, synthetic, deterministic local cartridge fixture packet."""

    cartridge_id: str
    display_name: str
    source_system: str
    readiness: str
    transform_spec_digest: str
    artifacts: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.cartridge_id) is not str or _CARTRIDGE_ID.fullmatch(self.cartridge_id) is None:
            raise CartridgePacketError("packet_cartridge_id")
        for name, value in (("display_name", self.display_name), ("source_system", self.source_system)):
            if type(value) is not str or not (3 <= len(value) <= 120) or any(ord(char) < 0x20 for char in value):
                raise CartridgePacketError(f"packet_{name}")
        if self.readiness != "synthetic_fixture":
            raise CartridgePacketError("packet_readiness")
        if type(self.transform_spec_digest) is not str or _DIGEST.fullmatch(self.transform_spec_digest) is None:
            raise CartridgePacketError("packet_transform_digest")
        if type(self.artifacts) is not dict or set(self.artifacts) != set(REQUIRED_PACKET_ARTIFACTS):
            raise CartridgePacketError("packet_artifact_set")
        for name in REQUIRED_PACKET_ARTIFACTS:
            if not isinstance(self.artifacts[name], (dict, list)):
                raise CartridgePacketError(f"packet_artifact_{name}")

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "cartridge_id": self.cartridge_id,
                "display_name": self.display_name,
                "source_system": self.source_system,
                "readiness": self.readiness,
                "transform_spec_digest": self.transform_spec_digest,
                "artifacts": self.artifacts,
            }
        )

    @property
    def reconciliation_digest(self) -> str:
        return canonical_digest(self.artifacts["reconciliation"])

    def ui_summary(self) -> dict[str, str | int]:
        """The bounded, local-only data allowed into the M4 lab UI."""

        snapshot = self.artifacts["snapshot"]
        silver = self.artifacts["silver"]
        invalid = self.artifacts["invalid"]
        return {
            "cartridgeId": self.cartridge_id,
            "displayName": self.display_name,
            "sourceSystem": self.source_system,
            "readiness": self.readiness,
            "packetDigest": self.digest,
            "transformSpecDigest": self.transform_spec_digest,
            "reconciliationDigest": self.reconciliation_digest,
            "snapshotRecords": len(snapshot) if isinstance(snapshot, list) else 0,
            "silverRecords": len(silver) if isinstance(silver, list) else 0,
            "invalidRecords": len(invalid) if isinstance(invalid, list) else 0,
        }


def load_packet(path: str | Path) -> CartridgePacket:
    """Load one local JSON packet without accepting an arbitrary file format."""

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CartridgePacketError("packet_load") from exc
    if type(raw) is not dict or tuple(sorted(raw)) != (
        "artifacts",
        "cartridge_id",
        "display_name",
        "readiness",
        "source_system",
        "transform_spec_digest",
    ):
        raise CartridgePacketError("packet_shape")
    return CartridgePacket(**raw)
