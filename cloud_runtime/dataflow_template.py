"""Fixed Apache Beam template for one trusted, sanitized source bundle.

No plan operation or generated code is evaluated here.  The earlier trusted
interpreter has already produced the protected output rows.  This template
only verifies their immutable bindings, flattens the closed cell envelope, and
writes them with lineage columns to the pre-approved BigQuery table.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import decimal
import json
import re
from collections.abc import Iterator, Mapping

from control_plane.canonical import (
    SCHEMA_VERSION,
    TARGET_TABLES,
    canonical_json_bytes,
    document_digest,
    require_digest,
    require_run_id,
    sha256_digest,
)


class TemplateInputRejected(ValueError):
    """A safe template-input rejection that never reflects bundle contents."""


_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_DATASET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_BQ_TYPES = {
    "string": "STRING",
    "integer": "INTEGER",
    "decimal": "NUMERIC",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "boolean": "BOOLEAN",
    "bytes": "BYTES",
}
_BUNDLE_KEYS = {
    "schemaVersion",
    "kind",
    "runId",
    "sourceId",
    "portfolioDigest",
    "planDigest",
    "approvalDigest",
    "policyDigest",
    "target",
    "outputFields",
    "recordCount",
    "outputDigest",
    "rows",
    "bundleDigest",
}
_LINEAGE_FIELDS = (
    {"name": "_ztm_run_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "_ztm_source_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "_ztm_plan_digest", "type": "STRING", "mode": "REQUIRED"},
    {"name": "_ztm_output_digest", "type": "STRING", "mode": "REQUIRED"},
    {"name": "_ztm_bundle_digest", "type": "STRING", "mode": "REQUIRED"},
    {"name": "_ztm_approval_digest", "type": "STRING", "mode": "REQUIRED"},
    {"name": "_ztm_policy_digest", "type": "STRING", "mode": "REQUIRED"},
    {"name": "_ztm_job_name", "type": "STRING", "mode": "REQUIRED"},
    {"name": "_ztm_row_ordinal", "type": "INTEGER", "mode": "REQUIRED"},
)


def _reject(code: str) -> None:
    raise TemplateInputRejected(code)


def _valid_value(value: object, declared_type: str, nullable: bool) -> bool:
    if value is None:
        return nullable
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "integer":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and -(2**63) <= value <= 2**63 - 1
        )
    if declared_type == "decimal" and isinstance(value, str):
        try:
            numeric = decimal.Decimal(value)
        except decimal.InvalidOperation:
            return False
        normalized = numeric.normalize()
        if normalized == 0:
            normalized = decimal.Decimal(0)
        return (
            numeric.is_finite()
            and abs(normalized) < decimal.Decimal("1e29")
            and normalized.as_tuple().exponent >= -9
        )
    if declared_type == "date" and isinstance(value, str):
        try:
            return dt.date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    if declared_type == "timestamp" and isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(
                value[:-1] + "+00:00" if value.endswith("Z") else value
            )
            return parsed.tzinfo is not None and parsed.utcoffset() is not None
        except ValueError:
            return False
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "bytes" and isinstance(value, str):
        try:
            return base64.b64encode(base64.b64decode(value, validate=True)).decode(
                "ascii"
            ) == value
        except (ValueError, TypeError):
            return False
    return False


def parse_table_spec(value: str) -> tuple[str, str, str]:
    """Parse and validate `project:dataset.table` without accepting decorators."""

    if not isinstance(value, str) or value.count(":") != 1 or value.count(".") != 1:
        _reject("template_table")
    project, rest = value.split(":", 1)
    dataset, table = rest.split(".", 1)
    if (
        _PROJECT_RE.fullmatch(project) is None
        or _DATASET_RE.fullmatch(dataset) is None
        or table not in TARGET_TABLES.values()
    ):
        _reject("template_table")
    return project, dataset, table


def bigquery_schema(output_fields: object) -> dict[str, object]:
    if not isinstance(output_fields, list) or not output_fields:
        _reject("template_schema")
    fields: list[dict[str, str]] = []
    seen: set[str] = set()
    for declaration in output_fields:
        if type(declaration) is not dict or set(declaration) != {
            "name",
            "type",
            "nullable",
        }:
            _reject("template_schema")
        name = declaration.get("name")
        declared_type = declaration.get("type")
        nullable = declaration.get("nullable")
        if (
            not isinstance(name, str)
            or _FIELD_RE.fullmatch(name) is None
            or name.startswith("_ztm_")
            or name in seen
            or declared_type not in _BQ_TYPES
            or type(nullable) is not bool
        ):
            _reject("template_schema")
        seen.add(name)
        fields.append(
            {
                "name": name,
                "type": _BQ_TYPES[str(declared_type)],
                "mode": "NULLABLE" if nullable else "REQUIRED",
            }
        )
    fields.extend(dict(item) for item in _LINEAGE_FIELDS)
    return {"fields": fields}


def validate_bundle_document(
    document: object,
    *,
    expected_run_id: str,
    expected_source_id: str,
    expected_portfolio_digest: str,
    expected_plan_digest: str,
    expected_bundle_digest: str,
    output_table: str,
) -> dict[str, object]:
    """Validate every execution binding before yielding any destination row."""

    if type(document) is not dict or set(document) != _BUNDLE_KEYS:
        _reject("template_bundle")
    if (
        document.get("schemaVersion") != SCHEMA_VERSION
        or document.get("kind") != "trusted-dataflow-bundle"
    ):
        _reject("template_bundle")
    try:
        require_run_id(expected_run_id)
        for digest in (
            expected_portfolio_digest,
            expected_plan_digest,
            expected_bundle_digest,
            document.get("approvalDigest"),
            document.get("policyDigest"),
            document.get("outputDigest"),
        ):
            require_digest(digest)
    except (TypeError, ValueError):
        _reject("template_binding")
    if expected_source_id not in TARGET_TABLES:
        _reject("template_binding")
    project, dataset, table = parse_table_spec(output_table)
    del project
    if (
        document.get("runId") != expected_run_id
        or document.get("sourceId") != expected_source_id
        or document.get("portfolioDigest") != expected_portfolio_digest
        or document.get("planDigest") != expected_plan_digest
        or document.get("bundleDigest") != expected_bundle_digest
        or table != TARGET_TABLES[expected_source_id]
        or document.get("target") != {"dataset": dataset, "table": table}
    ):
        _reject("template_binding")
    if document_digest(document, omit=("bundleDigest",)) != expected_bundle_digest:
        _reject("template_bundle_digest")

    schema = bigquery_schema(document.get("outputFields"))
    declarations = tuple(schema["fields"][:-len(_LINEAGE_FIELDS)])
    declared_names = tuple(str(field["name"]) for field in declarations)
    rows = document.get("rows")
    record_count = document.get("recordCount")
    if (
        not isinstance(rows, list)
        or type(record_count) is not int
        or record_count < 0
        or len(rows) != record_count
    ):
        _reject("template_count")
    for row in rows:
        if type(row) is not dict or set(row) != set(declared_names):
            _reject("template_rows")
        for declaration in declarations:
            name = str(declaration["name"])
            cell = row[name]
            if type(cell) is not dict or set(cell) != {"protection", "value"}:
                _reject("template_rows")
            if cell.get("protection") not in {"sanitized", "tokenized"}:
                _reject("template_rows")
            inverse_types = {value: key for key, value in _BQ_TYPES.items()}
            if not _valid_value(
                cell.get("value"),
                inverse_types[str(declaration["type"])],
                declaration["mode"] == "NULLABLE",
            ):
                _reject("template_rows")
    if sha256_digest(canonical_json_bytes(rows)) != document.get("outputDigest"):
        _reject("template_output_digest")
    return document


def destination_rows(
    document: Mapping[str, object], *, expected_job_name: str
) -> Iterator[dict[str, object]]:
    """Flatten validated protected cells and attach immutable lineage."""

    if re.fullmatch(r"[a-z][-a-z0-9]{2,62}", expected_job_name) is None:
        _reject("template_job_name")
    rows = document["rows"]
    if not isinstance(rows, list):  # validate_bundle_document owns this invariant
        _reject("template_rows")
    for ordinal, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            _reject("template_rows")
        row = {
            str(name): cell["value"]
            for name, cell in raw_row.items()
            if isinstance(cell, Mapping)
        }
        if len(row) != len(raw_row):
            _reject("template_rows")
        row.update(
            {
                "_ztm_run_id": document["runId"],
                "_ztm_source_id": document["sourceId"],
                "_ztm_plan_digest": document["planDigest"],
                "_ztm_output_digest": document["outputDigest"],
                "_ztm_bundle_digest": document["bundleDigest"],
                "_ztm_approval_digest": document["approvalDigest"],
                "_ztm_policy_digest": document["policyDigest"],
                "_ztm_job_name": expected_job_name,
                "_ztm_row_ordinal": ordinal,
            }
        )
        yield row


def _decode_and_validate(
    line: str,
    *,
    expected_run_id: str,
    expected_source_id: str,
    expected_portfolio_digest: str,
    expected_plan_digest: str,
    expected_bundle_digest: str,
    output_table: str,
    expected_bigquery_schema: Mapping[str, object],
    expected_job_name: str,
) -> Iterator[dict[str, object]]:
    try:
        document = json.loads(line)
    except Exception:
        _reject("template_json")
    validated = validate_bundle_document(
        document,
        expected_run_id=expected_run_id,
        expected_source_id=expected_source_id,
        expected_portfolio_digest=expected_portfolio_digest,
        expected_plan_digest=expected_plan_digest,
        expected_bundle_digest=expected_bundle_digest,
        output_table=output_table,
    )
    if bigquery_schema(validated["outputFields"]) != expected_bigquery_schema:
        _reject("template_schema_binding")
    yield from destination_rows(validated, expected_job_name=expected_job_name)


def run(argv: list[str] | None = None) -> None:
    """Construct the pre-built Beam graph; imports Beam only in the image."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input_uri", required=True)
    parser.add_argument("--output_table", required=True)
    parser.add_argument("--expected_run_id", required=True)
    parser.add_argument("--expected_source_id", required=True)
    parser.add_argument("--expected_portfolio_digest", required=True)
    parser.add_argument("--expected_plan_digest", required=True)
    parser.add_argument("--expected_bundle_digest", required=True)
    parser.add_argument("--output_schema_json", required=True)
    parser.add_argument("--expected_job_name", required=True)
    known, pipeline_args = parser.parse_known_args(argv)
    parse_table_spec(known.output_table)
    try:
        expected_bigquery_schema = json.loads(known.output_schema_json)
    except Exception:
        _reject("template_schema")
    if type(expected_bigquery_schema) is not dict:
        _reject("template_schema")

    import apache_beam as beam
    from apache_beam.options.pipeline_options import PipelineOptions

    with beam.Pipeline(options=PipelineOptions(pipeline_args)) as pipeline:
        rows = (
            pipeline
            | "Read immutable bundle" >> beam.io.ReadFromText(known.input_uri)
            | "Verify bindings"
            >> beam.FlatMap(
                _decode_and_validate,
                expected_run_id=known.expected_run_id,
                expected_source_id=known.expected_source_id,
                expected_portfolio_digest=known.expected_portfolio_digest,
                expected_plan_digest=known.expected_plan_digest,
                expected_bundle_digest=known.expected_bundle_digest,
                output_table=known.output_table,
                expected_bigquery_schema=expected_bigquery_schema,
                expected_job_name=known.expected_job_name,
            )
        )
        rows | "Write protected rows" >> beam.io.WriteToBigQuery(
            known.output_table,
            schema=expected_bigquery_schema,
            create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER,
            write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
            method=beam.io.WriteToBigQuery.Method.FILE_LOADS,
        )


if __name__ == "__main__":  # pragma: no cover - exercised by Dataflow image
    run()
