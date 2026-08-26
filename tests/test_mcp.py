"""Regression tests for the validation-only MCP compatibility service."""

import pytest

from sandbox_mcp import PlanValidationError, validate_plan


def test_safe_declarative_plan_returns_digest_without_execution():
    result = validate_plan(
        {
            "sourceId": "jde",
            "operations": [{"operation": "decode_text", "encoding": "ebcdic-cp037"}],
        }
    )
    assert result["status"] == "validated"
    assert result["executed"] is False
    assert len(result["digest"]) == 64


@pytest.mark.parametrize("key", ["code", "script", "command", "expression"])
def test_executable_content_is_rejected_recursively(key):
    with pytest.raises(PlanValidationError):
        validate_plan({"operations": [{key: "untrusted"}]})
