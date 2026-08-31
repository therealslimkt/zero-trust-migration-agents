from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "local_cartridge_agent.py"
SPEC = importlib.util.spec_from_file_location("local_cartridge_agent", MODULE_PATH)
assert SPEC and SPEC.loader
AGENT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AGENT
SPEC.loader.exec_module(AGENT)


def test_sanitize_evidence_accepts_only_the_count_contract():
    result = AGENT.sanitize_evidence(
        'untrusted docker noise\n{"schemaVersion":"keraun.cartridge-evidence/v1","synthetic":true,"checks":{"oracle_ebsUnmappedFlexfield":1}}\n'
        '{"schemaVersion":"keraun.cartridge-evidence/v1","synthetic":true,"checks":{"jdeInvalidCyyddd":1,"axOrphanDerived":2,"ebsUnmappedFlexfield":1}}\n'
    )
    assert result == {
        "schemaVersion": "keraun.cartridge-evidence/v1",
        "synthetic": True,
        "checks": {"axOrphanDerived": 2, "ebsUnmappedFlexfield": 1, "jdeInvalidCyyddd": 1},
    }


def test_sanitize_evidence_rejects_extra_or_non_count_output():
    with pytest.raises(AGENT.LocalAgentError, match="^evidence_shape$"):
        AGENT.sanitize_evidence('{"schemaVersion":"keraun.cartridge-evidence/v1","synthetic":true,"checks":{"jdeInvalidCyyddd":"1"}}')


def test_agent_token_is_required_and_printable():
    assert AGENT.require_token("x" * 32) == "x" * 32
    with pytest.raises(AGENT.LocalAgentError, match="^local_agent_token$"):
        AGENT.require_token("too-short")
