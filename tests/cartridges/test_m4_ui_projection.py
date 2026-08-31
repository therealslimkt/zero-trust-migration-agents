from __future__ import annotations

import json
from pathlib import Path

from cartridge_lab.m4 import build_m4_ui_projection


def test_checked_in_lab_projection_is_exact_verified_packet_projection() -> None:
    root = Path(__file__).resolve().parents[2]
    checked_in = json.loads(
        (root / "studio" / "src" / "web" / "pages" / "lab" / "m4FixtureData.json").read_text(
            encoding="utf-8"
        )
    )

    assert checked_in == build_m4_ui_projection()
