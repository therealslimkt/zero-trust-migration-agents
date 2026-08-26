"""Strict decoder for the deterministic clustered SAP MaxDB KNA1 export."""

from __future__ import annotations

import json
import re
import struct
import zlib

from edge_runtime.types import (
    SOURCE_SPECS,
    DecodedField,
    DecodedRecord,
    DecodedSource,
    SourcePayload,
)


HEADER = struct.Struct("<8sBBH")
ENTRY = struct.Struct("<III")
MAGIC = b"MXDBKNA1"
VERSION = 1
ZLIB_FLAGS = 1
MAX_RECORDS = 10_000
MAX_UNCOMPRESSED_BYTES = 16 * 1024
MAX_COMPRESSED_BYTES = 64 * 1024
EXPECTED_KEYS = frozenset({"KUNNR", "NAME1", "ORT01", "LAND1"})


class MaxDBDecodeError(ValueError):
    """Malformed-export error whose message never includes record values."""


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MaxDBDecodeError("JSON contains a duplicate key")
        result[key] = value
    return result


def _decode_record(raw: bytes, ordinal: int) -> DecodedRecord:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MaxDBDecodeError("record is not valid UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except json.JSONDecodeError as exc:
        raise MaxDBDecodeError("record is not valid JSON") from exc

    if not isinstance(value, dict):
        raise MaxDBDecodeError("record JSON must be an object")
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if canonical != raw:
        raise MaxDBDecodeError("record JSON is not canonical")
    if set(value) != EXPECTED_KEYS:
        raise MaxDBDecodeError("record JSON has missing or extra fields")
    if any(not isinstance(value[key], str) or not value[key].strip() for key in EXPECTED_KEYS):
        raise MaxDBDecodeError("record fields must be nonblank strings")
    if re.fullmatch(r"\d{10}", value["KUNNR"]) is None:
        raise MaxDBDecodeError("KUNNR must be exactly 10 decimal digits")
    if re.fullmatch(r"[A-Z]{2}", value["LAND1"]) is None:
        raise MaxDBDecodeError("LAND1 must be exactly two uppercase ASCII letters")

    return DecodedRecord(
        ordinal,
        (
            DecodedField("customer_number", value["KUNNR"], "financialAccount"),
            DecodedField("name", value["NAME1"], "name"),
            DecodedField("city", value["ORT01"], "address"),
            DecodedField("country", value["LAND1"], "public"),
        ),
    )


def _decompress(compressed: bytes, expected_length: int) -> bytes:
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(compressed, MAX_UNCOMPRESSED_BYTES + 1)
    except zlib.error as exc:
        raise MaxDBDecodeError("cluster contains invalid zlib data") from exc
    if len(raw) > MAX_UNCOMPRESSED_BYTES or decoder.unconsumed_tail:
        raise MaxDBDecodeError("cluster exceeds the uncompressed output limit")
    if not decoder.eof:
        raise MaxDBDecodeError("cluster zlib stream is incomplete")
    if decoder.unused_data:
        raise MaxDBDecodeError("cluster contains unused compressed bytes")
    if len(raw) != expected_length:
        raise MaxDBDecodeError("cluster uncompressed length does not match its header")
    return raw


def decode(payload: SourcePayload) -> DecodedSource:
    """Decode a complete canonical KNA1 export or reject it without partial output."""

    if not isinstance(payload, SourcePayload):
        raise MaxDBDecodeError("payload must be a SourcePayload")
    if payload.spec != SOURCE_SPECS["maxdb"]:
        raise MaxDBDecodeError("payload must use the canonical maxdb source specification")
    if not isinstance(payload.data, bytes):
        raise MaxDBDecodeError("payload data must be bytes")
    data = payload.data
    if len(data) < HEADER.size:
        raise MaxDBDecodeError("payload is too short for its header")

    magic, version, flags, record_count = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise MaxDBDecodeError("payload has an invalid magic number")
    if version != VERSION:
        raise MaxDBDecodeError("payload has an unsupported version")
    if flags != ZLIB_FLAGS:
        raise MaxDBDecodeError("payload has unsupported compression flags")
    if not 1 <= record_count <= MAX_RECORDS:
        raise MaxDBDecodeError("payload has an invalid record count")

    offset = HEADER.size
    records = []
    for ordinal in range(record_count):
        if offset + ENTRY.size > len(data):
            raise MaxDBDecodeError("payload is truncated at a cluster header")
        uncompressed_length, compressed_length, expected_crc = ENTRY.unpack_from(
            data, offset
        )
        offset += ENTRY.size
        if not 1 <= uncompressed_length <= MAX_UNCOMPRESSED_BYTES:
            raise MaxDBDecodeError("cluster declares an invalid uncompressed length")
        if not 1 <= compressed_length <= MAX_COMPRESSED_BYTES:
            raise MaxDBDecodeError("cluster declares an invalid compressed length")
        end = offset + compressed_length
        if end > len(data):
            raise MaxDBDecodeError("payload is truncated in a compressed cluster")
        raw = _decompress(data[offset:end], uncompressed_length)
        offset = end
        if zlib.crc32(raw) & 0xFFFFFFFF != expected_crc:
            raise MaxDBDecodeError("cluster checksum does not match its header")
        records.append(_decode_record(raw, ordinal))

    if offset != len(data):
        raise MaxDBDecodeError("payload contains trailing file bytes")
    return DecodedSource("maxdb", "KNA1", tuple(records))
