"""Validation-only compatibility service for migration pipeline plans.

This module previously exposed an `execute_python` MCP tool that ran
caller-supplied Python via `exec()`. That tool allowed unauthenticated
arbitrary code execution and has been removed entirely. No tool in this
module accepts or runs Python, shell, scripts, or arbitrary expressions.

The only capability offered now is `validate_pipeline_plan`, which accepts a
declarative JSON plan, recursively rejects any executable-looking keys, and
returns a stable digest of the plan. It never evaluates or executes plan
contents. Real pipeline execution is out of scope for this milestone and is
addressed by signed, pre-registered Dataflow templates with typed parameters.
"""

import hashlib
import json

try:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("ExecutionSandbox")
except ImportError:  # pragma: no cover - allows import without mcp installed
    mcp = None

# Keys that would indicate an attempt to smuggle executable content into a
# declarative plan. Checked recursively, case-insensitively, at every depth.
FORBIDDEN_PLAN_KEYS = frozenset({"code", "script", "command", "expression"})


class PlanValidationError(ValueError):
    """Raised when a submitted plan contains disallowed executable content."""


def _check_forbidden_keys(node, path="plan"):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.strip().lower() in FORBIDDEN_PLAN_KEYS:
                raise PlanValidationError(
                    f"forbidden key '{key}' found at {path}.{key}"
                )
            _check_forbidden_keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _check_forbidden_keys(item, f"{path}[{index}]")


def validate_plan(plan: dict) -> dict:
    """Validate a declarative JSON plan without executing it.

    Returns a dict describing the validation outcome. On success this
    includes a stable SHA-256 digest of the canonicalized plan. The plan is
    never evaluated, executed, or imported; this function only inspects its
    structure.
    """
    if not isinstance(plan, dict):
        raise PlanValidationError("plan must be a JSON object")

    _check_forbidden_keys(plan)

    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {"status": "validated", "digest": digest, "executed": False}


if mcp is not None:

    @mcp.tool()
    def validate_pipeline_plan(plan: dict) -> dict:
        """
        Validates a declarative migration pipeline plan (JSON) and returns a
        stable digest. This tool never executes, evaluates, or imports any
        part of the submitted plan. Plans containing a `code`, `script`,
        `command`, or `expression` key at any nesting depth are rejected.
        """
        try:
            return validate_plan(plan)
        except PlanValidationError as exc:
            return {"status": "rejected", "error": str(exc), "executed": False}

    # Expose the ASGI app for Uvicorn (Cloud Run compatibility). No route in
    # this app accepts or runs arbitrary code.
    app = mcp.sse_app()
else:  # pragma: no cover - only hit when mcp is not installed
    app = None
