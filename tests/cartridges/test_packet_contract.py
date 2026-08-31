from __future__ import annotations

import json

import pytest

from cartridge_lab import CartridgePacket, CartridgePacketError, canonical_digest, load_packet


def packet() -> CartridgePacket:
    artifacts = {name: [] for name in (
        "manifest", "metadata", "snapshot", "delta", "invalid", "bronze", "silver", "reconciliation"
    )}
    return CartridgePacket(
        cartridge_id="jde",
        display_name="JD Edwards",
        source_system="jd_edwards",
        readiness="synthetic_fixture",
        transform_spec_digest=canonical_digest({"fixture": "jde"}),
        artifacts=artifacts,
    )


def test_packet_digest_is_repeatable_and_ui_summary_is_bounded() -> None:
    value = packet()
    assert value.digest == value.digest
    assert value.ui_summary()["readiness"] == "synthetic_fixture"
    assert "dataflow" not in value.ui_summary()
    assert "bigquery" not in value.ui_summary()


def test_packet_evidence_is_defensively_immutable_and_digest_domain_is_portable() -> None:
    value = packet()
    before = value.digest
    exposed = value.artifacts
    exposed["silver"].append({"tampered": True})

    assert value.digest == before
    assert value.artifacts["silver"] == []
    with pytest.raises(CartridgePacketError, match="packet_noncanonical_value"):
        canonical_digest({"notPortable": float("nan")})
    with pytest.raises(CartridgePacketError, match="packet_noncanonical_value"):
        canonical_digest({"notPortable": 1 << 63})


def test_packet_rejects_non_synthetic_readiness_and_missing_artifacts() -> None:
    with pytest.raises(CartridgePacketError):
        CartridgePacket("jde", "JD Edwards", "jd_edwards", "cloud", canonical_digest({}), {})


def test_load_packet_uses_exact_shape(tmp_path) -> None:
    value = packet()
    path = tmp_path / "packet.json"
    path.write_text(json.dumps({
        "cartridge_id": value.cartridge_id,
        "display_name": value.display_name,
        "source_system": value.source_system,
        "readiness": value.readiness,
        "transform_spec_digest": value.transform_spec_digest,
        "artifacts": value.artifacts,
    }))
    assert load_packet(path).digest == value.digest
