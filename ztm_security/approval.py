"""Approval binding and non-overridable denial policy.

An ApprovalRecord binds one approver to one specific plan digest, one
timestamp, and one portfolio run ID. It authorizes exactly that plan for
exactly that run -- nothing else. A fixed set of denial categories can never
be authorized by any approval, regardless of who signs it.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import re

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUN_ID_RE = re.compile(r"^mig_[A-Za-z0-9]{12,64}$")


class PolicyDenied(Exception):
    """Raised when a requested action is denied by policy."""


# Categories that no approval can override. These are checked independently
# of any ApprovalRecord and always deny the action outright.
NON_OVERRIDABLE_DENIALS = frozenset(
    {
        "raw_pii",
        "arbitrary_execution",
        "public_source_database",
        "unapproved_run",
    }
)


@dataclasses.dataclass(frozen=True)
class ApprovalRecord:
    """A single approval, bound to one approver, plan digest, timestamp,
    and portfolio run ID.
    """

    approver: str
    plan_digest: str
    timestamp: str  # ISO-8601 UTC, e.g. "2026-08-26T12:00:00Z"
    portfolio_run_id: str

    def __post_init__(self) -> None:
        if not self.approver or not self.approver.strip():
            raise ValueError("approver is required")
        if not _DIGEST_RE.match(self.plan_digest or ""):
            raise ValueError("plan_digest must be a contract SHA-256 digest")
        if not self.timestamp:
            raise ValueError("timestamp is required")
        # Raises ValueError itself if not valid ISO-8601. A timezone is required
        # so approval ordering cannot depend on a process-local timezone.
        parsed_timestamp = _dt.datetime.fromisoformat(
            self.timestamp.replace("Z", "+00:00")
        )
        if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        if _RUN_ID_RE.fullmatch(self.portfolio_run_id or "") is None:
            raise ValueError("portfolio_run_id must be a contract migration run ID")


def check_non_overridable(categories) -> None:
    """Raise PolicyDenied if any category is a non-overridable denial.

    This check takes no ApprovalRecord on purpose: these categories cannot
    be approved around by any approver, digest, or run binding.
    """
    hit = NON_OVERRIDABLE_DENIALS.intersection(categories)
    if hit:
        raise PolicyDenied(f"non-overridable denial: {sorted(hit)}")


def authorize_run(
    record: ApprovalRecord,
    plan_digest: str,
    portfolio_run_id: str,
    categories=(),
) -> ApprovalRecord:
    """Authorize a run against a matching, well-formed ApprovalRecord.

    Fails closed: non-overridable categories are denied first regardless of
    the approval's validity, then the approval's plan digest and portfolio
    run ID must exactly match the requested execution context.
    """
    check_non_overridable(categories)

    if record.plan_digest != plan_digest:
        raise PolicyDenied("approval plan_digest does not match requested plan")
    if record.portfolio_run_id != portfolio_run_id:
        raise PolicyDenied("approval portfolio_run_id does not match requested run")

    return record
