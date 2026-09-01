"""Legacy Antigravity three-source implementation behind the v1 entry point."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence

import requests
from dotenv import load_dotenv
from google.antigravity import Agent, LocalAgentConfig


load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
MISSION_CONTROL_URL = os.environ.get(
    "MISSION_CONTROL_URL", "http://localhost:8080/api/status"
)


def _agent_config(instructions: str) -> LocalAgentConfig:
    return LocalAgentConfig(
        model=MODEL,
        vertex=True,
        location=VERTEX_LOCATION,
        tools=[],
        system_instructions=instructions,
    )


_PROFILER_CONFIG = _agent_config(
    """You are a legacy source profiler. You receive sanitized structural
metadata only. Return JSON describing fields, encodings, date formats, and
schema risks. Never request raw records or PII. Never generate code, scripts,
commands, SQL expressions, or executable content."""
)

_PLANNER_CONFIG = _agent_config(
    """You are the TransformPlan planner. Given three sanitized source
profiles, return one JSON object containing exactly three declarative plans.
Use only the allowlisted operations decode_text, packed_decimal, map_date,
rename, cast, drop, and tokenize. Never emit code, scripts, commands, SQL
expressions, or arbitrary expressions. Do not claim that a plan executed."""
)

_AUDITOR_CONFIG = _agent_config(
    """You are the portfolio plan auditor. Review a declarative plan for all
three sources. Return JSON with approvedForHumanReview, findings, and
evidence. Reject unknown operations, executable content, missing sources, or
any indication of raw PII. You cannot approve execution and cannot launch a
pipeline."""
)


def _report_status(agent: str, status: str, message: str) -> None:
    try:
        requests.post(
            MISSION_CONTROL_URL,
            json={"agent": agent, "status": status, "message": message},
            timeout=1,
        )
    except requests.RequestException:
        return


async def _profile_source(profile: dict[str, object]) -> dict[str, object]:
    source_id = str(profile["sourceId"])
    _report_status(source_id, "profiling", "Analyzing sanitized metadata")
    async with Agent(config=_PROFILER_CONFIG) as profiler:
        response = await profiler.chat(json.dumps(profile, sort_keys=True))
        result = json.loads(await response.text())
    _report_status(source_id, "profiled", "Sanitized profile ready")
    return {"sourceId": source_id, "profile": result}


async def run_v1_portfolio(
    source_profiles: Sequence[dict[str, object]],
) -> dict[str, object]:
    """Run the immutable v1 demonstration and stop at human review."""

    source_ids = tuple(str(profile.get("sourceId")) for profile in source_profiles)
    if source_ids != ("jde", "dynamics", "ebs"):
        raise ValueError("v1 portfolio requires exactly jde, dynamics, and ebs")
    _report_status("orchestrator", "profiling", "Dispatching three source profilers")
    profiles = await asyncio.gather(
        *(_profile_source(dict(profile)) for profile in source_profiles)
    )

    async with Agent(config=_PLANNER_CONFIG) as planner:
        response = await planner.chat(json.dumps({"profiles": profiles}, sort_keys=True))
        portfolio_plan = json.loads(await response.text())

    planned_sources = {
        plan.get("sourceId") for plan in portfolio_plan.get("plans", [])
    }
    if planned_sources != {"jde", "dynamics", "ebs"}:
        raise ValueError("portfolio plan must contain exactly jde, dynamics, and ebs")

    async with Agent(config=_AUDITOR_CONFIG) as auditor:
        response = await auditor.chat(json.dumps(portfolio_plan, sort_keys=True))
        audit = json.loads(await response.text())

    if audit.get("approvedForHumanReview") is not True:
        raise ValueError("portfolio plan failed audit and cannot be presented for approval")

    _report_status(
        "orchestrator",
        "awaiting_approval",
        "Three-source declarative portfolio plan is ready for human review",
    )
    return {
        "state": "awaiting_approval",
        "sources": ["jde", "dynamics", "ebs"],
        "plan": portfolio_plan,
        "audit": audit,
    }
