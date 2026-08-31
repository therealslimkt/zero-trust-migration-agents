"""Deterministic, local-only cartridge-fixture packets for Milestone 4.

This package contains no cloud client, deployer, or mutable production state.
It validates synthetic fixture evidence before it can be shown in the additive
Mission Control lab view.
"""

from .core import (
    REQUIRED_PACKET_ARTIFACTS,
    CartridgePacket,
    CartridgePacketError,
    canonical_digest,
    load_packet,
)

__all__ = [
    "REQUIRED_PACKET_ARTIFACTS",
    "CartridgePacket",
    "CartridgePacketError",
    "canonical_digest",
    "load_packet",
]
