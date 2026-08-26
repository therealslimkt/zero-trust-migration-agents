#!/usr/bin/env python3
"""Generate the deterministic synthetic clustered SAP MaxDB KNA1 export."""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path


COMPANIES = (
    {"KUNNR": "0000000001", "LAND1": "US", "NAME1": "Northstar Components LLC", "ORT01": "Chicago"},
    {"KUNNR": "0000000002", "LAND1": "CA", "NAME1": "Blue Heron Manufacturing Ltd", "ORT01": "Toronto"},
    {"KUNNR": "0000000003", "LAND1": "DE", "NAME1": "Juniper Industrial GmbH", "ORT01": "Berlin"},
    {"KUNNR": "0000000004", "LAND1": "JP", "NAME1": "Copper Finch Systems KK", "ORT01": "Tokyo"},
)


def build_maxdb_export(records=COMPANIES) -> bytes:
    chunks = [struct.pack("<8sBBH", b"MXDBKNA1", 1, 1, len(records))]
    for record in records:
        raw = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        compressed = zlib.compress(raw, level=9)
        chunks.append(
            struct.pack(
                "<III",
                len(raw),
                len(compressed),
                zlib.crc32(raw) & 0xFFFFFFFF,
            )
        )
        chunks.append(compressed)
    return b"".join(chunks)


def generate_maxdb_export(output_path: Path) -> None:
    output_path.write_bytes(build_maxdb_export())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic MaxDB KNA1 export"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("KNA1_clustered_export.bin"),
    )
    args = parser.parse_args()
    generate_maxdb_export(args.output)


if __name__ == "__main__":
    main()
