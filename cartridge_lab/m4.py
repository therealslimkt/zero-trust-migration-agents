"""Joined local evidence projection for the three-cartridge M4 slice."""

from __future__ import annotations

from cartridge_lab.ax import load_ax_packet
from cartridge_lab.jde import load_jde_packet
from cartridge_lab.oracle_ebs import build_oracle_ebs_packet


def build_m4_ui_projection() -> list[dict[str, str | int]]:
    """Return the sole bounded UI projection from verified local packets."""

    return [
        load_jde_packet().ui_summary(),
        load_ax_packet().ui_summary(),
        build_oracle_ebs_packet().ui_summary(),
    ]
