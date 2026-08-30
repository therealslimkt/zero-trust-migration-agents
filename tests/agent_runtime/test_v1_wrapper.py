from __future__ import annotations

import asyncio
from unittest import mock

import main


def test_main_delegates_exact_three_source_v1_portfolio_and_preserves_stop():
    expected = {
        "state": "awaiting_approval",
        "sources": ["jde", "maxdb", "btrieve"],
    }
    with mock.patch(
        "main.run_v1_portfolio", new=mock.AsyncMock(return_value=expected)
    ) as delegate:
        assert asyncio.run(main.run_orchestrator()) == expected
    delegate.assert_awaited_once_with(main.SANITIZED_SOURCE_PROFILES)


def test_main_rejects_a_v1_delegate_crossing_the_approval_boundary():
    with mock.patch(
        "main.run_v1_portfolio",
        new=mock.AsyncMock(return_value={"state": "succeeded"}),
    ):
        try:
            asyncio.run(main.run_orchestrator())
        except ValueError as exc:
            assert str(exc) == "v1 compatibility runtime crossed its approval boundary"
        else:
            raise AssertionError("v1 wrapper accepted a post-approval state")
