from __future__ import annotations

import unittest

from edge_runtime.adapters.jde import decode
from edge_runtime.types import SOURCE_SPECS, SourcePayload, SourceSpec


def _comp3(value: int, *, sign: str | None = None) -> bytes:
    digits = f"{abs(value):09d}"
    sign_nibble = sign or ("D" if value < 0 else "C")
    return bytes.fromhex(digits + sign_nibble)


def _record(
    address_number: int,
    alpha_name: str,
    tax_id: str,
    *,
    sign: str | None = None,
) -> bytes:
    return b"".join(
        (
            _comp3(address_number, sign=sign),
            alpha_name.ljust(40).encode("cp037"),
            tax_id.ljust(20).encode("cp037"),
        )
    )


def _payload(data: bytes) -> SourcePayload:
    return SourcePayload(spec=SOURCE_SPECS["jde"], data=data)


class JdeAdapterTests(unittest.TestCase):
    def test_decodes_multiple_records_with_ordered_fields(self) -> None:
        raw = _record(1001, "Example Industries", "TIN-EXAMPLE-01") + _record(
            1002, "Sample Logistics", "TIN-EXAMPLE-02"
        )

        decoded = decode(_payload(raw))

        self.assertEqual(decoded.source_id, "jde")
        self.assertEqual(decoded.record_set, "F0101")
        self.assertEqual(len(decoded.records), 2)
        self.assertEqual(decoded.records[0].ordinal, 0)
        self.assertEqual(
            [(field.name, field.category, field.value) for field in decoded.records[0].fields],
            [
                ("address_number", "public", 1001),
                ("alpha_name", "name", "Example Industries"),
                ("tax_id", "governmentId", "TIN-EXAMPLE-01"),
            ],
        )
        self.assertEqual(decoded.records[1].ordinal, 1)

    def test_accepts_negative_and_unsigned_positive_comp3_signs(self) -> None:
        raw = _record(-42, "Negative Example", "TIN-NEGATIVE", sign="D") + _record(
            73, "Unsigned Example", "TIN-UNSIGNED", sign="F"
        )

        decoded = decode(_payload(raw))

        self.assertEqual(decoded.records[0].fields[0].value, -42)
        self.assertEqual(decoded.records[1].fields[0].value, 73)

    def test_rejects_malformed_comp3_digit_without_exposing_values(self) -> None:
        raw = bytearray(_record(1, "Do Not Expose Name", "DO-NOT-EXPOSE-TAX"))
        raw[0] = 0xA0

        with self.assertRaisesRegex(ValueError, "malformed packed decimal") as raised:
            decode(_payload(bytes(raw)))

        self.assertNotIn("Do Not Expose", str(raised.exception))
        self.assertNotIn("DO-NOT-EXPOSE", str(raised.exception))

    def test_rejects_malformed_comp3_sign(self) -> None:
        raw = bytearray(_record(1, "Example Name", "TIN-EXAMPLE"))
        raw[4] = (raw[4] & 0xF0) | 0xB

        with self.assertRaisesRegex(ValueError, "malformed packed decimal"):
            decode(_payload(bytes(raw)))

    def test_rejects_empty_truncated_and_trailing_data(self) -> None:
        valid = _record(1, "Example Name", "TIN-EXAMPLE")
        invalid_payloads = (b"", valid[:-1], valid + b"\x00")

        for raw in invalid_payloads:
            with self.subTest(size=len(raw)):
                with self.assertRaises(ValueError):
                    decode(_payload(raw))

    def test_rejects_blank_required_text_fields(self) -> None:
        blank_alpha = _record(1, "", "TIN-EXAMPLE")
        blank_tax = _record(1, "Example Name", "")

        for raw in (blank_alpha, blank_tax):
            with self.subTest(raw=raw[:5]):
                with self.assertRaisesRegex(ValueError, "blank required text"):
                    decode(_payload(raw))

    def test_rejects_noncanonical_source(self) -> None:
        wrong_source = SourcePayload(
            spec=SOURCE_SPECS["maxdb"],
            data=_record(1, "Example Name", "TIN-EXAMPLE"),
        )
        altered_jde = SourcePayload(
            spec=SourceSpec(
                source_id="jde",
                hostname="unexpected-host",
                remote_path=SOURCE_SPECS["jde"].remote_path,
                source_format=SOURCE_SPECS["jde"].source_format,
            ),
            data=_record(1, "Example Name", "TIN-EXAMPLE"),
        )

        for payload in (wrong_source, altered_jde):
            with self.subTest(source=payload.spec.source_id):
                with self.assertRaisesRegex(ValueError, "canonical jde"):
                    decode(payload)

    def test_decoded_repr_hides_values(self) -> None:
        decoded = decode(
            _payload(_record(87654321, "Sensitive Example", "TAX-SENSITIVE-123"))
        )

        rendered = repr(decoded)
        self.assertNotIn("87654321", rendered)
        self.assertNotIn("Sensitive Example", rendered)
        self.assertNotIn("TAX-SENSITIVE-123", rendered)


if __name__ == "__main__":
    unittest.main()
