"""Closed local-fixture packet contract shared by the three M4 cartridges."""

from __future__ import annotations

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


def _canonical_json(value: object) -> str:
    """Serialize the deliberately narrow cross-runtime JSON evidence domain."""

    def validate(item: object) -> None:
        if item is None or type(item) in (bool, str):
            return
        if type(item) is int:
            if -(1 << 63) <= item <= (1 << 63) - 1:
                return
            raise CartridgePacketError("packet_noncanonical_value")
        if type(item) is list:
            for child in item:
                validate(child)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise CartridgePacketError("packet_noncanonical_value")
                validate(child)
            return
        raise CartridgePacketError("packet_noncanonical_value")

    validate(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CartridgePacketError("packet_noncanonical_value") from exc


def canonical_digest(value: object) -> str:
    """Return a stable digest for the narrow, portable fixture JSON domain."""

    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


class CartridgePacket:
    """A defensively immutable, synthetic local cartridge fixture packet."""

    __slots__ = (
        "cartridge_id",
        "display_name",
        "source_system",
        "readiness",
        "transform_spec_digest",
        "_artifacts_json",
    )

    def __init__(
        self,
        cartridge_id: str,
        display_name: str,
        source_system: str,
        readiness: str,
        transform_spec_digest: str,
        artifacts: Mapping[str, object],
    ) -> None:
        if type(cartridge_id) is not str or _CARTRIDGE_ID.fullmatch(cartridge_id) is None:
            raise CartridgePacketError("packet_cartridge_id")
        for name, value in (("display_name", display_name), ("source_system", source_system)):
            if type(value) is not str or not (3 <= len(value) <= 120) or any(ord(char) < 0x20 for char in value):
                raise CartridgePacketError(f"packet_{name}")
        if readiness != "synthetic_fixture":
            raise CartridgePacketError("packet_readiness")
        if type(transform_spec_digest) is not str or _DIGEST.fullmatch(transform_spec_digest) is None:
            raise CartridgePacketError("packet_transform_digest")
        if type(artifacts) is not dict or set(artifacts) != set(REQUIRED_PACKET_ARTIFACTS):
            raise CartridgePacketError("packet_artifact_set")
        for name in REQUIRED_PACKET_ARTIFACTS:
            if not isinstance(artifacts[name], (dict, list)):
                raise CartridgePacketError(f"packet_artifact_{name}")
        artifacts_json = _canonical_json(artifacts)
        object.__setattr__(self, "cartridge_id", cartridge_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "source_system", source_system)
        object.__setattr__(self, "readiness", readiness)
        object.__setattr__(self, "transform_spec_digest", transform_spec_digest)
        object.__setattr__(self, "_artifacts_json", artifacts_json)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("CartridgePacket is immutable")

    @property
    def artifacts(self) -> dict[str, object]:
        """Return a detached JSON copy; callers cannot mutate validated evidence."""

        return json.loads(self._artifacts_json)

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "cartridge_id": self.cartridge_id,
                "display_name": self.display_name,
                "source_system": self.source_system,
                "readiness": self.readiness,
                "transform_spec_digest": self.transform_spec_digest,
                "artifacts": json.loads(self._artifacts_json),
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
