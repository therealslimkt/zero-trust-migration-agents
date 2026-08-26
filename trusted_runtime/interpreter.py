"""Closed interpreter for approved transformations over sanitized records.

The module deliberately implements a very small data language.  Plans are
contract documents, never programs: only pre-registered operations are
dispatched, and neither plan nor record content is incorporated into errors.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import decimal
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_plane.canonical import (
    TARGET_TABLES,
    canonical_json_bytes,
    document_digest,
    sha256_digest,
)
from ztm_security.approval import ApprovalRecord, authorize_run


class ExecutionRejected(ValueError):
    """Raised when an artifact cannot be handled by the trusted interpreter."""


@dataclasses.dataclass(frozen=True)
class ExecutionResult:
    """Protected output and reconciliation evidence for one source plan."""

    source_id: str
    target: dict[str, str]
    rows: tuple[Mapping[str, Mapping[str, object]], ...] = dataclasses.field(
        repr=False
    )
    record_count: int
    output_digest: str

    def __post_init__(self) -> None:
        frozen_rows = tuple(
            MappingProxyType(
                {
                    field: MappingProxyType(dict(cell))
                    for field, cell in row.items()
                }
            )
            for row in self.rows
        )
        object.__setattr__(self, "rows", frozen_rows)

    def as_rows(self) -> tuple[dict[str, dict[str, object]], ...]:
        """Return detached rows for a trusted destination writer."""

        return tuple(
            {field: dict(cell) for field, cell in row.items()} for row in self.rows
        )


_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "contracts" / "schemas"
_CLOUD_OPERATIONS = frozenset({"rename", "cast", "drop"})
_EDGE_ONLY_OPERATIONS = frozenset(
    {"decode_text", "packed_decimal", "map_date", "tokenize"}
)
_INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")


def _load_schema(name: str) -> dict[str, object]:
    with (_SCHEMA_DIR / name).open(encoding="utf-8") as stream:
        document = json.load(stream)
    if not isinstance(document, dict):  # pragma: no cover - repository invariant
        raise RuntimeError("contract schema is not an object")
    return document


_COMMON_SCHEMA = _load_schema("common.schema.json")
_SCHEMA_REGISTRY = Registry().with_resource(
    str(_COMMON_SCHEMA["$id"]), Resource.from_contents(_COMMON_SCHEMA)
)
_PLAN_VALIDATOR = Draft202012Validator(
    _load_schema("transform-plan.schema.json"), registry=_SCHEMA_REGISTRY
)
_BATCH_VALIDATOR = Draft202012Validator(
    _load_schema("record-batch.schema.json"), registry=_SCHEMA_REGISTRY
)


@dataclasses.dataclass(frozen=True)
class _Cell:
    protection: str
    value: object = dataclasses.field(repr=False)


def _reject(code: str) -> None:
    raise ExecutionRejected(code)


def _validate_contract(
    validator: Draft202012Validator, artifact: object, error_code: str
) -> None:
    # Do not include jsonschema's error because it can echo artifact values.
    try:
        validator.validate(artifact)
    except Exception:
        _reject(error_code)


def _require_plain_mapping(value: object, error_code: str) -> dict[str, Any]:
    if type(value) is not dict:
        _reject(error_code)
    return value  # type: ignore[return-value]


def _check_finite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _reject("nonfinite_numeric")
    if isinstance(value, decimal.Decimal) and not value.is_finite():
        _reject("nonfinite_numeric")


def _records_from_batch(batch: Mapping[str, object]) -> list[dict[str, _Cell]]:
    raw_records = batch["records"]
    if not isinstance(raw_records, list):  # also guaranteed by schema
        _reject("batch_integrity")
    if batch["recordCount"] != len(raw_records):
        _reject("batch_record_count")

    ordinals: set[int] = set()
    record_ids: set[str] = set()
    records: list[dict[str, _Cell]] = []
    expected_fields: frozenset[str] | None = None

    for expected_ordinal, raw_record in enumerate(raw_records):
        record = _require_plain_mapping(raw_record, "batch_integrity")
        ordinal = record["ordinal"]
        record_id = record["recordId"]
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            _reject("batch_ordinals")
        if ordinal != expected_ordinal or ordinal in ordinals:
            _reject("batch_ordinals")
        if not isinstance(record_id, str) or record_id in record_ids:
            _reject("batch_record_ids")
        ordinals.add(ordinal)
        record_ids.add(record_id)

        cells: dict[str, _Cell] = {}
        raw_values = record["values"]
        if not isinstance(raw_values, list):
            _reject("batch_integrity")
        for raw_cell in raw_values:
            cell = _require_plain_mapping(raw_cell, "batch_integrity")
            field_name = cell["field"]
            if not isinstance(field_name, str) or field_name in cells:
                _reject("batch_fields")
            _check_finite(cell["value"])
            cells[field_name] = _Cell(
                protection=str(cell["protection"]), value=cell["value"]
            )

        field_set = frozenset(cells)
        if expected_fields is None:
            expected_fields = field_set
        elif field_set != expected_fields:
            _reject("batch_fields")
        records.append(cells)

    if ordinals != set(range(len(raw_records))):
        _reject("batch_ordinals")
    return records


def _require_field(records: list[dict[str, _Cell]], field: str) -> None:
    if not records or any(field not in record for record in records):
        _reject("operation_missing_field")


def _rename(records: list[dict[str, _Cell]], operation: Mapping[str, object]) -> None:
    old_name = str(operation["from"])
    new_name = str(operation["to"])
    _require_field(records, old_name)
    if old_name == new_name or any(new_name in record for record in records):
        _reject("rename_overwrite")
    for record in records:
        record[new_name] = record.pop(old_name)


def _drop(records: list[dict[str, _Cell]], operation: Mapping[str, object]) -> None:
    field = str(operation["field"])
    _require_field(records, field)
    for record in records:
        del record[field]


def _cast_string(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError from exc
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    if isinstance(value, (int, float)):
        _check_finite(value)
        return str(value)
    raise ValueError


def _cast_integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        _check_finite(value)
        if value.is_integer():
            return int(value)
        raise ValueError
    if isinstance(value, decimal.Decimal):
        _check_finite(value)
        if value == value.to_integral_value():
            return int(value)
        raise ValueError
    if isinstance(value, str) and _INTEGER_RE.fullmatch(value):
        return int(value)
    raise ValueError


def _cast_decimal(value: object) -> decimal.Decimal:
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, decimal.Decimal):
        result = value
    elif isinstance(value, (int, float, str)):
        if isinstance(value, float):
            _check_finite(value)
        try:
            result = decimal.Decimal(str(value))
        except decimal.InvalidOperation as exc:
            raise ValueError from exc
    else:
        raise ValueError
    _check_finite(result)
    return result


def _cast_date(value: object) -> dt.date:
    if isinstance(value, dt.datetime):
        raise ValueError
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError from exc
    raise ValueError


def _cast_timestamp(value: object) -> dt.datetime:
    result: dt.datetime
    if isinstance(value, dt.datetime):
        result = value
    elif isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            result = dt.datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError from exc
    else:
        raise ValueError
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError
    return result


def _cast_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    raise ValueError


def _cast_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise ValueError


_CASTERS: dict[str, Callable[[object], object]] = {
    "string": _cast_string,
    "integer": _cast_integer,
    "decimal": _cast_decimal,
    "date": _cast_date,
    "timestamp": _cast_timestamp,
    "boolean": _cast_boolean,
    "bytes": _cast_bytes,
}


def _cast(records: list[dict[str, _Cell]], operation: Mapping[str, object]) -> None:
    field = str(operation["field"])
    target_type = str(operation["targetType"])
    invalid_policy = str(operation["invalidPolicy"])
    _require_field(records, field)
    caster = _CASTERS[target_type]

    for record in records:
        cell = record[field]
        if cell.value is None:
            continue
        if cell.protection == "tokenized":
            if target_type != "string":
                _reject("tokenized_type_change")
            continue
        try:
            cast_value = caster(cell.value)
        except ExecutionRejected:
            raise
        except (TypeError, ValueError, OverflowError):
            if invalid_policy == "null":
                cast_value = None
            else:
                _reject("invalid_cast")
        record[field] = _Cell(protection=cell.protection, value=cast_value)


_HANDLERS: dict[
    str, Callable[[list[dict[str, _Cell]], Mapping[str, object]], None]
] = {"rename": _rename, "cast": _cast, "drop": _drop}


def _matches_type(value: object, declared_type: str) -> bool:
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "decimal":
        if isinstance(value, bool) or not isinstance(
            value, (int, float, decimal.Decimal)
        ):
            return False
        _check_finite(value)
        return True
    if declared_type == "date":
        return isinstance(value, dt.date) and not isinstance(value, dt.datetime)
    if declared_type == "timestamp":
        return isinstance(value, dt.datetime)
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "bytes":
        return isinstance(value, bytes)
    return False  # pragma: no cover - schema prevents unknown declarations


def _finish_rows(
    records: list[dict[str, _Cell]], output_fields: object
) -> tuple[dict[str, dict[str, object]], ...]:
    if not isinstance(output_fields, list):  # guaranteed by plan schema
        _reject("output_contract")
    declarations: dict[str, tuple[str, bool]] = {}
    for raw_declaration in output_fields:
        declaration = _require_plain_mapping(raw_declaration, "output_contract")
        name = str(declaration["name"])
        if name in declarations:
            _reject("output_duplicate_field")
        declarations[name] = (str(declaration["type"]), bool(declaration["nullable"]))

    expected = set(declarations)
    result: list[dict[str, dict[str, object]]] = []
    for record in records:
        if set(record) != expected:
            _reject("output_field_mismatch")
        row: dict[str, dict[str, object]] = {}
        # Declaration order is intentional and makes output stable even if
        # source value arrays arrive in a different order.
        for field, (declared_type, nullable) in declarations.items():
            cell = record[field]
            value = cell.value
            if value is None:
                if not nullable:
                    _reject("output_nullability")
            else:
                if cell.protection == "tokenized" and declared_type != "string":
                    _reject("tokenized_type_change")
                if not _matches_type(value, declared_type):
                    _reject("output_type")
            row[field] = {"protection": cell.protection, "value": value}
        result.append(row)
    return tuple(result)


def _digestable_value(value: object) -> object:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    _check_finite(value)
    return value


def _rows_digest(rows: tuple[dict[str, dict[str, object]], ...]) -> str:
    digest_rows = [
        {
            field: {
                "protection": cell["protection"],
                "value": _digestable_value(cell["value"]),
            }
            for field, cell in row.items()
        }
        for row in rows
    ]
    return sha256_digest(canonical_json_bytes(digest_rows))


def execute_plan(
    *,
    plan: dict,
    record_batch: dict,
    approval: ApprovalRecord,
    portfolio_digest: str,
    policy_categories,
) -> ExecutionResult:
    """Apply one approved declarative plan to one sanitized record batch.

    Authorization is completed before the record batch is validated or read.
    All errors are stable codes so neither source values nor tokenized values
    can be reflected into logs by an exception handler.
    """

    plan_document = _require_plain_mapping(plan, "plan_contract")
    _validate_contract(_PLAN_VALIDATOR, plan_document, "plan_contract")

    if document_digest(plan_document, omit=("planDigest",)) != plan_document["planDigest"]:
        _reject("plan_digest")

    # The approval is for the whole three-source portfolio and exact run.  It
    # must be checked before any batch records are inspected.
    authorize_run(
        approval,
        portfolio_digest,
        str(plan_document["runId"]),
        categories=policy_categories,
    )

    batch_document = _require_plain_mapping(record_batch, "batch_contract")
    _validate_contract(_BATCH_VALIDATOR, batch_document, "batch_contract")

    for key in ("runId", "sourceId", "sourceManifestDigest"):
        if plan_document[key] != batch_document[key]:
            _reject("plan_batch_mismatch")

    source_id = str(plan_document["sourceId"])
    target = _require_plain_mapping(plan_document["target"], "plan_contract")
    if target["table"] != TARGET_TABLES[source_id]:
        _reject("target_not_registered")

    records = _records_from_batch(batch_document)
    operations = plan_document["operations"]
    if not isinstance(operations, list):  # guaranteed by plan schema
        _reject("plan_contract")
    for raw_operation in operations:
        operation = _require_plain_mapping(raw_operation, "plan_contract")
        operation_name = str(operation["operation"])
        if operation_name in _EDGE_ONLY_OPERATIONS:
            _reject("edge_operation_in_cloud")
        if operation_name not in _CLOUD_OPERATIONS:
            _reject("unknown_operation")
        _HANDLERS[operation_name](records, operation)

    rows = _finish_rows(records, plan_document["outputFields"])
    return ExecutionResult(
        source_id=source_id,
        target={"dataset": str(target["dataset"]), "table": str(target["table"])},
        rows=rows,
        record_count=len(rows),
        output_digest=_rows_digest(rows),
    )
