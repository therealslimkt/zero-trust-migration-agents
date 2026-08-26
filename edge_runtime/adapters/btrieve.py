"""Strict Accpac/Btrieve adapter for the deterministic simulator format.

The accepted file is exactly two 4096-byte pages:

* page 0 -- File Control Block, ``<4sH`` header of signature ``FCB `` and the
  declared page size, followed by zero fill;
* page 1 -- data page, ``<IB`` header of next-page pointer ``0xFFFFFFFF`` and
  page type ``0x00``, then one ``<H40sf`` record at offset 5, followed by zero
  fill.

Anything else is rejected outright: this adapter never returns a partial record
set, and its error messages carry structural facts only, never legacy values.
"""

from __future__ import annotations

import math
import struct

from ..types import (
    DecodedField,
    DecodedRecord,
    DecodedSource,
    SourcePayload,
    get_source_spec,
)

SOURCE_ID = "btrieve"
RECORD_SET = "ARCUS_CUSTOMER"

PAGE_SIZE = 4096
PAGE_COUNT = 2
EXPECTED_SIZE = PAGE_SIZE * PAGE_COUNT

FCB_HEADER = struct.Struct("<4sH")
FCB_SIGNATURE = b"FCB "

DATA_HEADER = struct.Struct("<IB")
DATA_NEXT_PAGE = 0xFFFFFFFF
DATA_PAGE_TYPE = 0x00

RECORD = struct.Struct("<H40sf")
RECORD_OFFSET = DATA_HEADER.size
DECLARED_RECORD_LENGTH = RECORD.size
CUSTOMER_CODE_SIZE = 40

_PRINTABLE_ASCII = range(0x20, 0x7F)


class BtrieveDecodeError(ValueError):
    """Raised for any malformed Btrieve payload.

    Instances are constructed with structural descriptions only so that a
    legacy customer code or balance can never reach a log or an exception
    chain outside the edge trust boundary.
    """


def decode(payload: SourcePayload) -> DecodedSource:
    """Decode a canonical Btrieve payload, or raise :class:`BtrieveDecodeError`."""

    _require_canonical_source(payload)
    data = _require_bytes(payload.data)

    _decode_fcb_page(data)
    _decode_data_page_header(data)
    declared_length, raw_code, raw_balance = RECORD.unpack_from(
        data, PAGE_SIZE + RECORD_OFFSET
    )
    if declared_length != DECLARED_RECORD_LENGTH:
        raise BtrieveDecodeError(
            f"record declares length {declared_length}, expected "
            f"{DECLARED_RECORD_LENGTH}"
        )
    _require_zero_fill(
        data,
        PAGE_SIZE + RECORD_OFFSET + RECORD.size,
        EXPECTED_SIZE,
        "page 1 record trailer",
    )

    customer_code = _decode_customer_code(raw_code)
    balance = _decode_balance(raw_balance)

    record = DecodedRecord(
        ordinal=0,
        fields=(
            DecodedField(name="customer_code", value=customer_code, category="other"),
            DecodedField(
                name="account_balance", value=balance, category="financialAccount"
            ),
        ),
    )
    return DecodedSource(SOURCE_ID, RECORD_SET, (record,))


def _require_canonical_source(payload: SourcePayload) -> None:
    if not isinstance(payload, SourcePayload):
        raise BtrieveDecodeError("payload must be a SourcePayload")
    if payload.spec != get_source_spec(SOURCE_ID):
        raise BtrieveDecodeError(
            f"payload does not match the canonical {SOURCE_ID} source spec"
        )


def _require_bytes(data: object) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise BtrieveDecodeError("payload data must be bytes")
    data = bytes(data)
    if len(data) != EXPECTED_SIZE:
        raise BtrieveDecodeError(
            f"expected exactly {EXPECTED_SIZE} bytes, got {len(data)}"
        )
    return data


def _decode_fcb_page(data: bytes) -> None:
    signature, page_size = FCB_HEADER.unpack_from(data, 0)
    if signature != FCB_SIGNATURE:
        raise BtrieveDecodeError("page 0 does not carry the FCB signature")
    if page_size != PAGE_SIZE:
        raise BtrieveDecodeError(
            f"page 0 declares page size {page_size}, expected {PAGE_SIZE}"
        )
    _require_zero_fill(data, FCB_HEADER.size, PAGE_SIZE, "page 0 trailer")


def _decode_data_page_header(data: bytes) -> None:
    next_page, page_type = DATA_HEADER.unpack_from(data, PAGE_SIZE)
    if next_page != DATA_NEXT_PAGE:
        raise BtrieveDecodeError(
            f"page 1 next-page pointer is 0x{next_page:08X}, expected "
            f"0x{DATA_NEXT_PAGE:08X}"
        )
    if page_type != DATA_PAGE_TYPE:
        raise BtrieveDecodeError(
            f"page 1 type is 0x{page_type:02X}, expected 0x{DATA_PAGE_TYPE:02X}"
        )


def _require_zero_fill(data: bytes, start: int, stop: int, label: str) -> None:
    if any(data[start:stop]):
        raise BtrieveDecodeError(f"{label} contains nonzero unused bytes")


def _decode_customer_code(raw: bytes) -> str:
    if len(raw) != CUSTOMER_CODE_SIZE:
        raise BtrieveDecodeError(
            f"customer code field is {len(raw)} bytes, expected {CUSTOMER_CODE_SIZE}"
        )
    padding_start = raw.find(b"\x00")
    if padding_start == -1:
        body = raw
    else:
        body = raw[:padding_start]
        padding = raw[padding_start:]
        if padding.count(0) != len(padding):
            raise BtrieveDecodeError("customer code padding is not NUL filled")
    if not body:
        raise BtrieveDecodeError("customer code is blank")
    if any(byte not in _PRINTABLE_ASCII for byte in body):
        raise BtrieveDecodeError("customer code is not printable ASCII")
    code = body.decode("ascii")
    if not code.strip():
        raise BtrieveDecodeError("customer code is blank")
    return code


def _decode_balance(raw: float) -> float:
    if not math.isfinite(raw):
        raise BtrieveDecodeError("account balance is not a finite float32")
    return float(raw)
