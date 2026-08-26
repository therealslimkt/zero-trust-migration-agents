"""Build immutable, approval-bound inputs for the fixed Dataflow template.

The trusted interpreter produces protected in-memory rows.  This module is the
only bridge from those rows to cloud storage.  It revalidates the portfolio,
approval, source order, targets, schemas, counts, and output digests before it
serializes anything.  Errors are stable codes and never contain row values.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import decimal
import json
import math
import re
from collections.abc import Iterable, Mapping

from control_plane.canonical import (
    SCHEMA_VERSION,
    SOURCE_ORDER,
    TARGET_TABLES,
    canonical_json_bytes,
    document_digest,
    portfolio_plan_digest,
    require_digest,
    require_run_id,
    sha256_digest,
)
from control_plane.workflow import PreparedPortfolio, PortfolioExecutionResult
from ztm_security.approval import ApprovalRecord, authorize_run


class CloudBundleRejected(ValueError):
    """A fail-closed rejection with a safe, repository-owned error code."""


_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_TOKEN_RE = re.compile(r"^tok_[A-Za-z0-9_-]{8,256}$")
_ALLOWED_TYPES = frozenset(
    {"string", "integer", "decimal", "date", "timestamp", "boolean", "bytes"}
)
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_NUMERIC_LIMIT = decimal.Decimal("1e29")


def _reject(code: str) -> None:
    raise CloudBundleRejected(code)


@dataclasses.dataclass(frozen=True)
class CloudBundle:
    """One immutable canonical object ready for create-only cloud storage."""

    source_id: str
    object_name: str
    digest: str
    payload: bytes = dataclasses.field(repr=False)

    def as_document(self) -> dict[str, object]:
        return json.loads(self.payload)


def _approval_digest(approval: ApprovalRecord) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {
                "approver": approval.approver,
                "planDigest": approval.plan_digest,
                "portfolioRunId": approval.portfolio_run_id,
                "timestamp": approval.timestamp,
            }
        )
    )


def _output_declarations(plan: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    raw = plan.get("outputFields")
    if not isinstance(raw, list) or not raw:
        _reject("cloud_plan_schema")
    declarations: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in raw:
        if type(item) is not dict or set(item) != {"name", "type", "nullable"}:
            _reject("cloud_plan_schema")
        name = item.get("name")
        declared_type = item.get("type")
        nullable = item.get("nullable")
        if (
            not isinstance(name, str)
            or _FIELD_RE.fullmatch(name) is None
            or name.startswith("_ztm_")
            or name in seen
            or declared_type not in _ALLOWED_TYPES
            or type(nullable) is not bool
        ):
            _reject("cloud_plan_schema")
        seen.add(name)
        declarations.append(
            {"name": name, "type": declared_type, "nullable": nullable}
        )
    return tuple(declarations)


def _json_value(value: object, declared_type: str, nullable: bool) -> object:
    if value is None:
        if not nullable:
            _reject("cloud_row_nullability")
        return None
    if declared_type == "string" and isinstance(value, str):
        return value
    if declared_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
        if _INT64_MIN <= value <= _INT64_MAX:
            return value
        _reject("cloud_numeric_domain")
    if declared_type == "decimal" and not isinstance(value, bool):
        numeric: decimal.Decimal | None = None
        if isinstance(value, decimal.Decimal):
            if value.is_finite():
                numeric = value
        elif isinstance(value, int):
            numeric = decimal.Decimal(value)
        elif isinstance(value, float) and math.isfinite(value):
            numeric = decimal.Decimal(str(value))
        if numeric is not None:
            normalized = numeric.normalize()
            if normalized == 0:
                normalized = decimal.Decimal(0)
            if abs(normalized) < _NUMERIC_LIMIT and normalized.as_tuple().exponent >= -9:
                return format(normalized, "f")
            _reject("cloud_numeric_domain")
    if declared_type == "date" and isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value.isoformat()
    if declared_type == "timestamp" and isinstance(value, dt.datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value.isoformat()
    if declared_type == "boolean" and isinstance(value, bool):
        return value
    if declared_type == "bytes" and isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    _reject("cloud_row_type")


def _canonical_rows(
    rows: object, declarations: tuple[dict[str, object], ...]
) -> tuple[dict[str, dict[str, object]], ...]:
    if not isinstance(rows, tuple):
        _reject("cloud_rows")
    expected = tuple(str(item["name"]) for item in declarations)
    canonical_rows: list[dict[str, dict[str, object]]] = []
    for raw_row in rows:
        if not isinstance(raw_row, Mapping) or set(raw_row) != set(expected):
            _reject("cloud_row_fields")
        row: dict[str, dict[str, object]] = {}
        for declaration in declarations:
            name = str(declaration["name"])
            raw_cell = raw_row[name]
            if not isinstance(raw_cell, Mapping) or set(raw_cell) != {
                "protection",
                "value",
            }:
                _reject("cloud_row_protection")
            protection = raw_cell["protection"]
            if protection not in {"sanitized", "tokenized"}:
                _reject("cloud_row_protection")
            value = _json_value(
                raw_cell["value"],
                str(declaration["type"]),
                bool(declaration["nullable"]),
            )
            if protection == "tokenized":
                if (
                    declaration["type"] != "string"
                    or not isinstance(value, str)
                    or _TOKEN_RE.fullmatch(value) is None
                ):
                    _reject("cloud_token")
            row[name] = {"protection": protection, "value": value}
        canonical_rows.append(row)
    return tuple(canonical_rows)


def _validated_inputs(
    prepared: PreparedPortfolio,
    execution: PortfolioExecutionResult,
    approval: ApprovalRecord,
    policy_categories: Iterable[str],
) -> tuple[dict[str, object], tuple[object, ...], frozenset[str]]:
    if not isinstance(prepared, PreparedPortfolio):
        _reject("cloud_prepared")
    if not isinstance(execution, PortfolioExecutionResult):
        _reject("cloud_execution")
    if not isinstance(approval, ApprovalRecord):
        _reject("cloud_approval")
    if isinstance(policy_categories, (str, bytes)):
        _reject("cloud_policy")
    try:
        categories = frozenset(policy_categories)
        if any(not isinstance(category, str) for category in categories):
            _reject("cloud_policy")
        authorize_run(
            approval,
            prepared.portfolio_digest,
            prepared.run_id,
            categories=categories,
        )
    except Exception:
        _reject("cloud_approval")
    if (
        execution.run_id != prepared.run_id
        or execution.portfolio_digest != prepared.portfolio_digest
        or len(execution.reconciliations) != len(SOURCE_ORDER)
    ):
        _reject("cloud_execution_binding")
    document = prepared.as_document()
    if type(document) is not dict or set(document) != {
        "schemaVersion",
        "runId",
        "portfolioDigest",
        "model",
        "sources",
    }:
        _reject("cloud_prepared")
    if document.get("schemaVersion") != SCHEMA_VERSION:
        _reject("cloud_prepared")
    try:
        require_run_id(str(document["runId"]))
        require_digest(str(document["portfolioDigest"]))
    except (TypeError, ValueError):
        _reject("cloud_prepared")
    raw_sources = document.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != len(SOURCE_ORDER):
        _reject("cloud_prepared")
    plans: list[dict[str, object]] = []
    for expected_source_id, raw_source in zip(SOURCE_ORDER, raw_sources):
        if type(raw_source) is not dict or raw_source.get("sourceId") != expected_source_id:
            _reject("cloud_source_order")
        plan = raw_source.get("plan")
        if (
            type(plan) is not dict
            or plan.get("runId") != document["runId"]
            or plan.get("sourceId") != expected_source_id
        ):
            _reject("cloud_plan_binding")
        plan_digest = plan.get("planDigest")
        try:
            require_digest(plan_digest)
        except (TypeError, ValueError):
            _reject("cloud_plan_binding")
        if document_digest(plan, omit=("planDigest",)) != plan_digest:
            _reject("cloud_plan_digest")
        plans.append(plan)
    try:
        recomputed_portfolio_digest = portfolio_plan_digest(plans)
    except (TypeError, ValueError):
        _reject("cloud_portfolio_digest")
    if recomputed_portfolio_digest != document["portfolioDigest"]:
        _reject("cloud_portfolio_digest")
    return document, tuple(execution.reconciliations), categories


def build_cloud_bundles(
    *,
    prepared: PreparedPortfolio,
    execution: PortfolioExecutionResult,
    approval: ApprovalRecord,
    policy_categories: Iterable[str],
) -> tuple[CloudBundle, ...]:
    """Return exactly three create-only bundle payloads in canonical order."""

    document, results, categories = _validated_inputs(
        prepared, execution, approval, policy_categories
    )
    policy_digest = sha256_digest(
        canonical_json_bytes(
            {
                "schemaVersion": SCHEMA_VERSION,
                "nonOverridableCategories": sorted(categories),
            }
        )
    )
    raw_sources = document["sources"]
    bundles: list[CloudBundle] = []
    for source_id, raw_source, result in zip(SOURCE_ORDER, raw_sources, results):
        if type(raw_source) is not dict or raw_source.get("sourceId") != source_id:
            _reject("cloud_source_order")
        plan = raw_source.get("plan")
        if type(plan) is not dict:
            _reject("cloud_plan")
        plan_digest = plan.get("planDigest")
        try:
            require_digest(plan_digest)
        except (TypeError, ValueError):
            _reject("cloud_plan")
        if document_digest(plan, omit=("planDigest",)) != plan_digest:
            _reject("cloud_plan_digest")
        target = plan.get("target")
        if (
            type(target) is not dict
            or set(target) != {"dataset", "table"}
            or target.get("table") != TARGET_TABLES[source_id]
        ):
            _reject("cloud_target")
        if (
            getattr(result, "source_id", None) != source_id
            or getattr(result, "target", None) != target
        ):
            _reject("cloud_execution_binding")
        declarations = _output_declarations(plan)
        rows = _canonical_rows(getattr(result, "rows", None), declarations)
        row_count = getattr(result, "row_count", None)
        output_digest = getattr(result, "output_digest", None)
        if type(row_count) is not int or row_count < 0 or row_count != len(rows):
            _reject("cloud_row_count")
        try:
            require_digest(output_digest)
        except (TypeError, ValueError):
            _reject("cloud_output_digest")
        if sha256_digest(canonical_json_bytes(rows)) != output_digest:
            _reject("cloud_output_digest")

        payload_document: dict[str, object] = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "trusted-dataflow-bundle",
            "runId": document["runId"],
            "sourceId": source_id,
            "portfolioDigest": document["portfolioDigest"],
            "planDigest": plan_digest,
            "approvalDigest": _approval_digest(approval),
            "policyDigest": policy_digest,
            "target": dict(target),
            "outputFields": list(declarations),
            "recordCount": row_count,
            "outputDigest": output_digest,
            "rows": list(rows),
        }
        payload_document["bundleDigest"] = document_digest(payload_document)
        payload = canonical_json_bytes(payload_document)
        digest = str(payload_document["bundleDigest"])
        object_name = (
            f"runs/{document['runId']}/{source_id}/{digest.removeprefix('sha256:')}.json"
        )
        bundles.append(
            CloudBundle(
                source_id=source_id,
                object_name=object_name,
                digest=digest,
                payload=payload,
            )
        )
    return tuple(bundles)
