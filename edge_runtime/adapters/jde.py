"""Strict decoder for synthetic JDE/AS400 F0101 binary exports."""

from __future__ import annotations

from edge_runtime.types import (
    SOURCE_SPECS,
    DecodedField,
    DecodedRecord,
    DecodedSource,
    SourcePayload,
)


_RECORD_SIZE = 65
_ABAN8_SIZE = 5
_ABALPH_SIZE = 40
_VALID_COMP3_SIGNS = frozenset({0xC, 0xD, 0xF})


def _decode_comp3(raw: bytes) -> int:
    nibbles: list[int] = []
    for byte in raw:
        nibbles.extend((byte >> 4, byte & 0x0F))

    digits = nibbles[:-1]
    sign = nibbles[-1]
    if any(digit > 9 for digit in digits) or sign not in _VALID_COMP3_SIGNS:
        raise ValueError("JDE record contains malformed packed decimal")

    magnitude = 0
    for digit in digits:
        magnitude = (magnitude * 10) + digit
    return -magnitude if sign == 0xD else magnitude


def _decode_required_text(raw: bytes) -> str:
    try:
        value = raw.decode("cp037").rstrip(" ")
    except UnicodeError:
        raise ValueError("JDE record contains malformed text") from None
    if not value.strip():
        raise ValueError("JDE record contains blank required text")
    return value


def decode(payload: SourcePayload) -> DecodedSource:
    """Decode a complete F0101 payload or reject it without partial output."""

    if payload.spec != SOURCE_SPECS["jde"]:
        raise ValueError("JDE payload must use the canonical jde source specification")
    if not payload.data:
        raise ValueError("JDE payload is empty")
    if len(payload.data) % _RECORD_SIZE:
        raise ValueError("JDE payload length must be an exact record multiple")

    records: list[DecodedRecord] = []
    for ordinal, offset in enumerate(range(0, len(payload.data), _RECORD_SIZE)):
        raw = payload.data[offset : offset + _RECORD_SIZE]
        address_number = _decode_comp3(raw[:_ABAN8_SIZE])
        alpha_name = _decode_required_text(
            raw[_ABAN8_SIZE : _ABAN8_SIZE + _ABALPH_SIZE]
        )
        tax_id = _decode_required_text(raw[_ABAN8_SIZE + _ABALPH_SIZE :])
        records.append(
            DecodedRecord(
                ordinal=ordinal,
                fields=(
                    DecodedField("address_number", address_number, "public"),
                    DecodedField("alpha_name", alpha_name, "name"),
                    DecodedField("tax_id", tax_id, "governmentId"),
                ),
            )
        )

    return DecodedSource("jde", "F0101", tuple(records))
