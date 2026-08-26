"""Gemini portfolio-planning prototype.

This entry point intentionally stops at the human approval boundary. Runtime
agents may create declarative TransformPlans, but they never generate or
execute Python, shell, Beam source, or arbitrary expressions.
"""

import asyncio
import json
import os

import requests
from dotenv import load_dotenv
from google.antigravity import Agent, LocalAgentConfig

load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
MISSION_CONTROL_URL = os.environ.get(
    "MISSION_CONTROL_URL", "http://localhost:8080/api/status"
)

SANITIZED_SOURCE_PROFILES = (
    {
        "sourceId": "jde",
        "hostname": "legacy-jde-db",
        "format": "jde-as400",
        "metadata": {"table": "F0101", "encoding": "ebcdic-cp037"},
    },
    {
        "sourceId": "maxdb",
        "hostname": "legacy-maxdb",
        "format": "sap-maxdb",
        "metadata": {"table": "KNA1", "encoding": "utf-8"},
    },
    {
        "sourceId": "btrieve",
        "hostname": "legacy-btrieve-db",
        "format": "accpac-btrieve",
        "metadata": {"table": "ARCUS", "encoding": "binary-records"},
    },
)


def agent_config(instructions: str) -> LocalAgentConfig:
    return LocalAgentConfig(
        model=MODEL,
        vertex=True,
        location=VERTEX_LOCATION,
        tools=[],
        system_instructions=instructions,
    )


profiler_config = agent_config(
    """You are a legacy source profiler. You receive sanitized structural
metadata only. Return JSON describing fields, encodings, date formats, and
schema risks. Never request raw records or PII. Never generate code, scripts,
commands, SQL expressions, or executable content."""
)

planner_config = agent_config(
    """You are the TransformPlan planner. Given three sanitized source
profiles, return one JSON object containing exactly three declarative plans.
Use only the allowlisted operations decode_text, packed_decimal, map_date,
rename, cast, drop, and tokenize. Never emit code, scripts, commands, SQL
expressions, or arbitrary expressions. Do not claim that a plan executed."""
)

auditor_config = agent_config(
    """You are the portfolio plan auditor. Review a declarative plan for all
three sources. Return JSON with approvedForHumanReview, findings, and
evidence. Reject unknown operations, executable content, missing sources, or
any indication of raw PII. You cannot approve execution and cannot launch a
pipeline."""
)


def report_status(agent: str, status: str, message: str) -> None:
    try:
        requests.post(
            MISSION_CONTROL_URL,
            json={"agent": agent, "status": status, "message": message},
            timeout=1,
        )
    except requests.RequestException:
        return


async def profile_source(profile: dict) -> dict:
    report_status(profile["sourceId"], "profiling", "Analyzing sanitized metadata")
    async with Agent(config=profiler_config) as profiler:
        response = await profiler.chat(json.dumps(profile, sort_keys=True))
        result = json.loads(await response.text())
    report_status(profile["sourceId"], "profiled", "Sanitized profile ready")
    return {"sourceId": profile["sourceId"], "profile": result}


async def run_orchestrator() -> dict:
    report_status("orchestrator", "profiling", "Dispatching three source profilers")
    profiles = await asyncio.gather(
        *(profile_source(profile) for profile in SANITIZED_SOURCE_PROFILES)
    )

    async with Agent(config=planner_config) as planner:
        response = await planner.chat(json.dumps({"profiles": profiles}, sort_keys=True))
        portfolio_plan = json.loads(await response.text())

    planned_sources = {
        plan.get("sourceId") for plan in portfolio_plan.get("plans", [])
    }
    if planned_sources != {"jde", "maxdb", "btrieve"}:
        raise ValueError("portfolio plan must contain exactly jde, maxdb, and btrieve")

    async with Agent(config=auditor_config) as auditor:
        response = await auditor.chat(json.dumps(portfolio_plan, sort_keys=True))
        audit = json.loads(await response.text())

    if audit.get("approvedForHumanReview") is not True:
        raise ValueError("portfolio plan failed audit and cannot be presented for approval")

    report_status(
        "orchestrator",
        "awaiting_approval",
        "Three-source declarative portfolio plan is ready for human review",
    )
    return {
        "state": "awaiting_approval",
        "sources": ["jde", "maxdb", "btrieve"],
        "plan": portfolio_plan,
        "audit": audit,
    }


if __name__ == "__main__":
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        raise SystemExit("GOOGLE_CLOUD_PROJECT is required for Vertex AI")
    result = asyncio.run(run_orchestrator())
    print(json.dumps(result, indent=2, sort_keys=True))
