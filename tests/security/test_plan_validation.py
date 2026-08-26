"""Behavioral tests for the validation-only pipeline plan service.

These import the actual validation functions (not just scanning source) to
prove they reject executable keys at any nesting depth and return a stable
digest, without executing anything.
"""

import hashlib
import json

import pytest

import sandbox_mcp
import tools.mcp_sandbox as tools_mcp_sandbox

MODULES = [sandbox_mcp, tools_mcp_sandbox]

SAFE_PLAN = {
    "source": {"table": "legacy_customers"},
    "steps": [
        {"op": "rename_column", "from": "cust_nm", "to": "customer_name"},
        {"op": "cast", "column": "balance", "type": "NUMERIC"},
    ],
    "destination": {"dataset": "migrated", "table": "customers"},
}


@pytest.mark.parametrize("module", MODULES)
def test_safe_plan_is_validated_and_not_executed(module):
    result = module.validate_plan(SAFE_PLAN)
    assert result["status"] == "validated"
    assert result["executed"] is False
    assert isinstance(result["digest"], str) and len(result["digest"]) == 64


@pytest.mark.parametrize("module", MODULES)
def test_digest_is_stable_across_calls(module):
    first = module.validate_plan(SAFE_PLAN)
    second = module.validate_plan(SAFE_PLAN)
    assert first["digest"] == second["digest"]


@pytest.mark.parametrize("module", MODULES)
def test_digest_matches_expected_sha256_of_canonical_json(module):
    canonical = json.dumps(SAFE_PLAN, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    result = module.validate_plan(SAFE_PLAN)
    assert result["digest"] == expected


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("forbidden_key", ["code", "script", "command", "expression"])
def test_top_level_forbidden_key_is_rejected(module, forbidden_key):
    plan = {forbidden_key: "print('should never run')"}
    with pytest.raises(module.PlanValidationError):
        module.validate_plan(plan)


@pytest.mark.parametrize("module", MODULES)
def test_deeply_nested_forbidden_key_is_rejected(module):
    plan = {
        "steps": [
            {
                "op": "transform",
                "nested": {
                    "further": [
                        {"harmless": True},
                        {"expression": "os.system('rm -rf /')"},
                    ]
                },
            }
        ]
    }
    with pytest.raises(module.PlanValidationError):
        module.validate_plan(plan)


@pytest.mark.parametrize("module", MODULES)
def test_forbidden_key_check_is_case_insensitive(module):
    plan = {"steps": [{"Command": "whoami"}]}
    with pytest.raises(module.PlanValidationError):
        module.validate_plan(plan)


@pytest.mark.parametrize("module", MODULES)
def test_non_dict_plan_is_rejected(module):
    with pytest.raises(module.PlanValidationError):
        module.validate_plan(["not", "a", "dict"])
