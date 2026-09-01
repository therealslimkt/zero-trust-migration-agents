"""V1 compatibility wrapper for the immutable three-source demonstration.

The ADK 2 enterprise fleet is assembled under :mod:`agent_runtime`; this entry
point deliberately preserves the existing v1 behavior and approval stop.
"""

from __future__ import annotations

import asyncio
import json
import os

from agent_runtime.v1_compat import run_v1_portfolio


SANITIZED_SOURCE_PROFILES = (
    {
        "sourceId": "jde",
        "hostname": "legacy-jde-db",
        "format": "jde-as400",
        "metadata": {"table": "F0101", "encoding": "ebcdic-cp037"},
    },
    {
        "sourceId": "dynamics",
        "hostname": "dynamics-ax",
        "format": "dynamics-ax-2012-custtable",
        "metadata": {"table": "CustTable", "encoding": "utf-8"},
    },
    {
        "sourceId": "ebs",
        "hostname": "oracle-ebs-19c",
        "format": "oracle-ebs-19c-hz-parties",
        "metadata": {"table": "HZ_PARTIES", "encoding": "utf-8"},
    },
)


async def run_orchestrator() -> dict[str, object]:
    """Delegate to v1 while preserving the exact human-approval boundary."""

    result = await run_v1_portfolio(SANITIZED_SOURCE_PROFILES)
    if result.get("state") != "awaiting_approval":
        raise ValueError("v1 compatibility runtime crossed its approval boundary")
    return result


if __name__ == "__main__":
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        raise SystemExit("GOOGLE_CLOUD_PROJECT is required for Vertex AI")
    print(json.dumps(asyncio.run(run_orchestrator()), indent=2, sort_keys=True))
