import importlib.util
import sys
from pathlib import Path

import pytest

APPROVAL_PATH = Path(__file__).resolve().parents[2] / "ztm_security" / "approval.py"
SPEC = importlib.util.spec_from_file_location("ztm_approval_policy", APPROVAL_PATH)
approval_policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = approval_policy
SPEC.loader.exec_module(approval_policy)

ApprovalRecord = approval_policy.ApprovalRecord
PolicyDenied = approval_policy.PolicyDenied
authorize_run = approval_policy.authorize_run
check_non_overridable = approval_policy.check_non_overridable

VALID_DIGEST = "a" * 64


def make_record(**overrides):
    fields = {
        "approver": "alice@example.com",
        "plan_digest": VALID_DIGEST,
        "timestamp": "2026-08-26T12:00:00Z",
        "portfolio_run_id": "run-42",
    }
    fields.update(overrides)
    return ApprovalRecord(**fields)


def test_valid_approval_record_constructs():
    record = make_record()
    assert record.approver == "alice@example.com"
    assert record.plan_digest == VALID_DIGEST
    assert record.portfolio_run_id == "run-42"


@pytest.mark.parametrize(
    "overrides",
    [
        {"approver": ""},
        {"plan_digest": "not-a-digest"},
        {"plan_digest": "a" * 63},
        {"timestamp": ""},
        {"timestamp": "not-a-timestamp"},
        {"portfolio_run_id": ""},
    ],
)
def test_malformed_approval_record_rejected(overrides):
    with pytest.raises(ValueError):
        make_record(**overrides)


def test_authorize_run_succeeds_for_matching_digest_and_run():
    record = make_record()
    result = authorize_run(record, plan_digest=VALID_DIGEST, portfolio_run_id="run-42")
    assert result is record


def test_authorize_run_denies_digest_mismatch():
    record = make_record()
    with pytest.raises(PolicyDenied):
        authorize_run(record, plan_digest="b" * 64, portfolio_run_id="run-42")


def test_authorize_run_denies_portfolio_run_id_mismatch():
    record = make_record()
    with pytest.raises(PolicyDenied):
        authorize_run(record, plan_digest=VALID_DIGEST, portfolio_run_id="run-99")


@pytest.mark.parametrize(
    "category",
    ["raw_pii", "arbitrary_execution", "public_source_database", "unapproved_run"],
)
def test_non_overridable_categories_always_denied(category):
    with pytest.raises(PolicyDenied):
        check_non_overridable({category})


def test_non_overridable_denial_wins_even_with_valid_matching_approval():
    record = make_record()
    with pytest.raises(PolicyDenied):
        authorize_run(
            record,
            plan_digest=VALID_DIGEST,
            portfolio_run_id="run-42",
            categories={"raw_pii"},
        )


def test_overridable_category_does_not_trigger_non_overridable_denial():
    # A category outside the fixed denial set is not itself a policy
    # violation at this layer; it simply passes the non-overridable check.
    check_non_overridable({"routine_migration"})
