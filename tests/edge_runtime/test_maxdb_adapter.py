from __future__ import annotations

import json
import struct
import unittest
import zlib
from pathlib import Path

from edge_runtime.adapters import maxdb
from edge_runtime.types import SOURCE_SPECS, SourcePayload, SourceSpec
from tools.simulator.maxdb_kna1_generator import COMPANIES, build_maxdb_export


SAFE_RECORD = {
    "KUNNR": "0000000001",
    "LAND1": "US",
    "NAME1": "Synthetic Company",
    "ORT01": "Chicago",
}


def cluster(raw: bytes) -> bytes:
    compressed = zlib.compress(raw, level=9)
    return struct.pack(
        "<III", len(raw), len(compressed), zlib.crc32(raw) & 0xFFFFFFFF
    ) + compressed


def record_bytes(record=SAFE_RECORD) -> bytes:
    return json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def payload(data: bytes) -> SourcePayload:
    return SourcePayload(SOURCE_SPECS["maxdb"], data)


def file_with_raw(raw: bytes) -> bytes:
    return maxdb.HEADER.pack(maxdb.MAGIC, 1, 1, 1) + cluster(raw)


class MaxDBAdapterTests(unittest.TestCase):
    def test_generator_and_checked_fixture_are_identical(self):
        fixture = Path("tools/simulator/KNA1_clustered_export.bin").read_bytes()
        self.assertEqual(fixture, build_maxdb_export())
        self.assertEqual(len(maxdb.decode(payload(fixture)).records), len(COMPANIES))

    def test_decodes_ordered_fields_and_safe_repr(self):
        decoded = maxdb.decode(payload(build_maxdb_export()))
        self.assertEqual(decoded.source_id, "maxdb")
        self.assertEqual(decoded.record_set, "KNA1")
        self.assertEqual(
            [(field.name, field.category) for field in decoded.records[0].fields],
            [
                ("customer_number", "financialAccount"),
                ("name", "name"),
                ("city", "address"),
                ("country", "public"),
            ],
        )
        self.assertNotIn(COMPANIES[0]["NAME1"], repr(decoded))

    def test_rejects_noncanonical_source(self):
        altered = SourceSpec(
            "maxdb",
            "legacy-maxdb",
            "/home/kohalloran/not-the-export.bin",
            SOURCE_SPECS["maxdb"].source_format,
        )
        with self.assertRaisesRegex(maxdb.MaxDBDecodeError, "canonical"):
            maxdb.decode(SourcePayload(altered, build_maxdb_export()))

    def test_rejects_header_violations(self):
        valid = bytearray(build_maxdb_export())
        cases = []
        cases.append(b"short")
        bad_magic = bytearray(valid)
        bad_magic[:8] = b"BADMAGIC"
        cases.append(bytes(bad_magic))
        bad_version = bytearray(valid)
        bad_version[8] = 2
        cases.append(bytes(bad_version))
        bad_flags = bytearray(valid)
        bad_flags[9] = 0
        cases.append(bytes(bad_flags))
        no_records = bytearray(valid)
        struct.pack_into("<H", no_records, 10, 0)
        cases.append(bytes(no_records))
        for data in cases:
            with self.subTest(size=len(data)):
                with self.assertRaises(maxdb.MaxDBDecodeError):
                    maxdb.decode(payload(data))

    def test_rejects_truncation_and_trailing_bytes(self):
        valid = build_maxdb_export()
        for data in (valid[: maxdb.HEADER.size + 3], valid[:-1], valid + b"x"):
            with self.subTest(size=len(data)):
                with self.assertRaises(maxdb.MaxDBDecodeError):
                    maxdb.decode(payload(data))

    def test_rejects_invalid_lengths_checksum_and_zlib(self):
        raw = record_bytes()
        compressed = zlib.compress(raw)
        header = maxdb.HEADER.pack(maxdb.MAGIC, 1, 1, 1)
        cases = (
            header + maxdb.ENTRY.pack(0, len(compressed), 0) + compressed,
            header + maxdb.ENTRY.pack(len(raw), 0, 0),
            header + maxdb.ENTRY.pack(len(raw), 8, 0) + b"not-zlib",
            header + maxdb.ENTRY.pack(len(raw), len(compressed), 0) + compressed,
        )
        for data in cases:
            with self.subTest(size=len(data)):
                with self.assertRaises(maxdb.MaxDBDecodeError):
                    maxdb.decode(payload(data))

    def test_rejects_bomb_and_unused_stream_bytes(self):
        bomb_raw = b"A" * (maxdb.MAX_UNCOMPRESSED_BYTES + 1)
        bomb_compressed = zlib.compress(bomb_raw)
        bomb = (
            maxdb.HEADER.pack(maxdb.MAGIC, 1, 1, 1)
            + maxdb.ENTRY.pack(1, len(bomb_compressed), zlib.crc32(bomb_raw))
            + bomb_compressed
        )
        raw = record_bytes()
        double_stream = zlib.compress(raw) + zlib.compress(b"extra")
        unused = (
            maxdb.HEADER.pack(maxdb.MAGIC, 1, 1, 1)
            + maxdb.ENTRY.pack(len(raw), len(double_stream), zlib.crc32(raw))
            + double_stream
        )
        for data in (bomb, unused):
            with self.subTest(size=len(data)):
                with self.assertRaises(maxdb.MaxDBDecodeError):
                    maxdb.decode(payload(data))

    def test_rejects_noncanonical_or_invalid_record_json(self):
        noncanonical = json.dumps(SAFE_RECORD, indent=2).encode("utf-8")
        missing = dict(SAFE_RECORD)
        del missing["ORT01"]
        extra = dict(SAFE_RECORD, EXTRA="x")
        bad_number = dict(SAFE_RECORD, KUNNR="000000000X")
        bad_country = dict(SAFE_RECORD, LAND1="u1")
        blank_name = dict(SAFE_RECORD, NAME1="   ")
        invalid_records = (
            noncanonical,
            record_bytes(missing),
            record_bytes(extra),
            record_bytes(bad_number),
            record_bytes(bad_country),
            record_bytes(blank_name),
            b"[]",
            b"not-json",
            b"\xff",
        )
        for raw in invalid_records:
            with self.subTest(size=len(raw)):
                with self.assertRaises(maxdb.MaxDBDecodeError) as caught:
                    maxdb.decode(payload(file_with_raw(raw)))
                self.assertNotIn("000000000X", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
