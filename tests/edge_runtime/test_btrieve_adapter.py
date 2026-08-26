"""Adversarial tests for the strict Btrieve/Accpac adapter.

Every fixture is synthesized here from struct definitions; no raw legacy data
file is read or copied. The synthetic customer code and balance below are
fixture-only values used to prove that they never leak into a repr or an error
message.
"""

from __future__ import annotations

import math
import struct
import unittest

from edge_runtime.adapters import btrieve
from edge_runtime.types import SOURCE_SPECS, SourcePayload


FIXTURE_CODE = "SAGE_ACCPAC_CUSTOMER_01"
FIXTURE_BALANCE = 1530.5
FIXTURE_LEAK_MARKERS = ("SAGE_ACCPAC", "CUSTOMER_01", "1530")

PAGE_SIZE = btrieve.PAGE_SIZE
RECORD_START = PAGE_SIZE + btrieve.RECORD_OFFSET
RECORD_END = RECORD_START + btrieve.RECORD.size


def code_bytes(text: str = FIXTURE_CODE) -> bytes:
    """Pad an ASCII code to the fixed 40-byte NUL-padded field."""

    return text.encode("ascii").ljust(btrieve.CUSTOMER_CODE_SIZE, b"\x00")


def build_file(
    *,
    signature: bytes = btrieve.FCB_SIGNATURE,
    page_size: int = PAGE_SIZE,
    next_page: int = btrieve.DATA_NEXT_PAGE,
    page_type: int = btrieve.DATA_PAGE_TYPE,
    record_length: int = btrieve.DECLARED_RECORD_LENGTH,
    raw_code: bytes | None = None,
    balance: float = FIXTURE_BALANCE,
) -> bytearray:
    """Synthesize a two-page Btrieve image, canonical unless overridden."""

    fcb_page = bytearray(PAGE_SIZE)
    struct.pack_into("<4sH", fcb_page, 0, signature, page_size)

    data_page = bytearray(PAGE_SIZE)
    struct.pack_into("<IB", data_page, 0, next_page, page_type)
    struct.pack_into(
        "<H40sf",
        data_page,
        btrieve.RECORD_OFFSET,
        record_length,
        code_bytes() if raw_code is None else raw_code,
        balance,
    )
    return fcb_page + data_page


def payload(data: bytes | bytearray, source_id: str = "btrieve") -> SourcePayload:
    return SourcePayload(spec=SOURCE_SPECS[source_id], data=bytes(data))


def canonical_payload() -> SourcePayload:
    return payload(build_file())


class BtrieveHappyPathTests(unittest.TestCase):
    def test_decodes_canonical_payload(self) -> None:
        decoded = btrieve.decode(canonical_payload())

        self.assertEqual(decoded.source_id, "btrieve")
        self.assertEqual(decoded.record_set, "ARCUS_CUSTOMER")
        self.assertEqual(len(decoded.records), 1)

        record = decoded.records[0]
        self.assertEqual(record.ordinal, 0)
        self.assertEqual(
            [field.name for field in record.fields],
            ["customer_code", "account_balance"],
        )

        code_field, balance_field = record.fields
        self.assertEqual(code_field.value, FIXTURE_CODE)
        self.assertEqual(code_field.category, "other")
        self.assertIsInstance(balance_field.value, float)
        self.assertEqual(balance_field.value, FIXTURE_BALANCE)
        self.assertEqual(balance_field.category, "financialAccount")

    def test_accepts_code_filling_the_whole_field(self) -> None:
        full = "C" * btrieve.CUSTOMER_CODE_SIZE
        decoded = btrieve.decode(payload(build_file(raw_code=full.encode("ascii"))))
        self.assertEqual(decoded.records[0].fields[0].value, full)

    def test_accepts_negative_and_zero_balances(self) -> None:
        for balance in (-2048.25, 0.0):
            with self.subTest(balance=balance):
                decoded = btrieve.decode(payload(build_file(balance=balance)))
                self.assertEqual(decoded.records[0].fields[1].value, balance)

    def test_decode_is_deterministic(self) -> None:
        first = btrieve.decode(canonical_payload())
        second = btrieve.decode(canonical_payload())
        self.assertEqual(first, second)
        self.assertEqual(repr(first), repr(second))

    def test_repr_never_exposes_legacy_values(self) -> None:
        decoded = btrieve.decode(canonical_payload())
        rendered = " ".join(
            [
                repr(decoded),
                repr(decoded.records[0]),
                repr(decoded.records[0].fields[0]),
                repr(decoded.records[0].fields[1]),
            ]
        )
        for marker in FIXTURE_LEAK_MARKERS:
            self.assertNotIn(marker, rendered)


class BtrieveRejectionTests(unittest.TestCase):
    def assert_rejects(self, data: bytes | bytearray, *, source_id: str = "btrieve"):
        """Assert decode raises, and that the message leaks no legacy value."""

        with self.assertRaises(btrieve.BtrieveDecodeError) as ctx:
            btrieve.decode(payload(data, source_id=source_id))
        self.assertIsInstance(ctx.exception, ValueError)
        message = str(ctx.exception)
        for marker in FIXTURE_LEAK_MARKERS:
            self.assertNotIn(marker, message)
        return ctx.exception

    def test_rejects_wrong_source_spec(self) -> None:
        for source_id in ("jde", "maxdb"):
            with self.subTest(source_id=source_id):
                self.assert_rejects(build_file(), source_id=source_id)

    def test_rejects_non_payload_input(self) -> None:
        with self.assertRaises(btrieve.BtrieveDecodeError):
            btrieve.decode(bytes(build_file()))

    def test_rejects_non_bytes_data(self) -> None:
        with self.assertRaises(btrieve.BtrieveDecodeError):
            btrieve.decode(SourcePayload(spec=SOURCE_SPECS["btrieve"], data="FCB "))

    def test_rejects_wrong_total_size(self) -> None:
        canonical = build_file()
        for label, data in (
            ("empty", b""),
            ("truncated", canonical[:-1]),
            ("single page", canonical[:PAGE_SIZE]),
            ("trailing byte", canonical + b"\x00"),
            ("extra page", canonical + bytearray(PAGE_SIZE)),
        ):
            with self.subTest(case=label):
                self.assert_rejects(data)

    def test_rejects_bad_fcb_signature(self) -> None:
        for signature in (b"FCB\x00", b"MKD ", b"\x00\x00\x00\x00"):
            with self.subTest(signature=signature):
                self.assert_rejects(build_file(signature=signature))

    def test_rejects_wrong_declared_page_size(self) -> None:
        for page_size in (0, 512, 1024, 2048, 8192):
            with self.subTest(page_size=page_size):
                self.assert_rejects(build_file(page_size=page_size))

    def test_rejects_nonzero_unused_bytes_in_fcb_page(self) -> None:
        for offset in (btrieve.FCB_HEADER.size, 2048, PAGE_SIZE - 1):
            with self.subTest(offset=offset):
                data = build_file()
                data[offset] = 0x01
                self.assert_rejects(data)

    def test_rejects_bad_next_page_pointer(self) -> None:
        for next_page in (0x00000000, 0x00000002, 0xFFFFFFFE):
            with self.subTest(next_page=next_page):
                self.assert_rejects(build_file(next_page=next_page))

    def test_rejects_bad_page_type(self) -> None:
        for page_type in (0x01, 0x0C, 0xFF):
            with self.subTest(page_type=page_type):
                self.assert_rejects(build_file(page_type=page_type))

    def test_rejects_wrong_declared_record_length(self) -> None:
        for record_length in (0, 45, 47, 64, 0xFFFF):
            with self.subTest(record_length=record_length):
                self.assert_rejects(build_file(record_length=record_length))

    def test_rejects_nonzero_unused_bytes_in_data_page(self) -> None:
        for offset in (RECORD_END, RECORD_END + 1, 2 * PAGE_SIZE - 1):
            with self.subTest(offset=offset):
                data = build_file()
                data[offset] = 0x7F
                self.assert_rejects(data)

    def test_rejects_second_record_appended_after_the_first(self) -> None:
        data = build_file()
        struct.pack_into(
            "<H40sf",
            data,
            RECORD_END,
            btrieve.DECLARED_RECORD_LENGTH,
            code_bytes("SHADOW_RECORD"),
            1.0,
        )
        self.assert_rejects(data)

    def test_rejects_blank_customer_code(self) -> None:
        for label, raw in (
            ("all NUL", b""),
            ("spaces", b"    "),
            ("single space", b" "),
        ):
            with self.subTest(case=label):
                self.assert_rejects(build_file(raw_code=raw))

    def test_rejects_non_ascii_customer_code(self) -> None:
        for label, raw in (
            ("high bit", b"CUST\xff\x01"),
            ("latin-1", "CUSTÖMER".encode("latin-1")),
            ("control char", b"CUST\x07OMER"),
            ("delete char", b"CUST\x7fOMER"),
        ):
            with self.subTest(case=label):
                self.assert_rejects(build_file(raw_code=raw))

    def test_rejects_non_nul_padding_after_customer_code(self) -> None:
        for label, raw in (
            ("embedded NUL", b"CUST\x00OMER"),
            ("trailing junk", b"CUST" + b"\x00" * 20 + b"X"),
            ("space padded", b"CUST\x00" + b" " * 10),
        ):
            with self.subTest(case=label):
                padded = raw.ljust(btrieve.CUSTOMER_CODE_SIZE, b"\x00")
                self.assert_rejects(build_file(raw_code=padded))

    def test_rejects_non_finite_balance(self) -> None:
        for label, balance in (
            ("nan", float("nan")),
            ("+inf", float("inf")),
            ("-inf", float("-inf")),
        ):
            with self.subTest(case=label):
                self.assert_rejects(build_file(balance=balance))

    def test_rejects_balance_overflowing_float32(self) -> None:
        data = build_file()
        struct.pack_into("<I", data, RECORD_END - 4, 0x7F800000)
        self.assert_rejects(data)

    def test_no_partial_decode_when_balance_is_invalid(self) -> None:
        """A valid code plus an invalid balance still yields nothing."""

        with self.assertRaises(btrieve.BtrieveDecodeError):
            btrieve.decode(payload(build_file(balance=float("nan"))))

    def test_error_messages_are_structural_only(self) -> None:
        error = self.assert_rejects(build_file(page_size=512))
        self.assertIn("512", str(error))
        self.assertNotIn(str(FIXTURE_BALANCE), str(error))


class BtrieveFixtureSanityTests(unittest.TestCase):
    """Guard the fixture builder itself, so rejections mean what they claim."""

    def test_builder_matches_the_frozen_layout(self) -> None:
        data = build_file()
        self.assertEqual(len(data), btrieve.EXPECTED_SIZE)
        self.assertEqual(btrieve.RECORD.size, 46)
        self.assertEqual(btrieve.RECORD_OFFSET, 5)
        self.assertEqual(data[:6], struct.pack("<4sH", b"FCB ", PAGE_SIZE))
        self.assertEqual(
            data[PAGE_SIZE : PAGE_SIZE + 5], struct.pack("<IB", 0xFFFFFFFF, 0x00)
        )
        self.assertFalse(any(data[6:PAGE_SIZE]))
        self.assertFalse(any(data[RECORD_END:]))

    def test_fixture_balance_is_exact_in_float32(self) -> None:
        (roundtripped,) = struct.unpack("<f", struct.pack("<f", FIXTURE_BALANCE))
        self.assertEqual(roundtripped, FIXTURE_BALANCE)
        self.assertTrue(math.isfinite(roundtripped))


if __name__ == "__main__":
    unittest.main()
