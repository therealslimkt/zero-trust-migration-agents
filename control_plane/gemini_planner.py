"""Gemini-backed compiler for closed, declarative migration plans."""

from __future__ import annotations

import copy
import dataclasses
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Optional, Union

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from control_plane.canonical import (
    SCHEMA_VERSION,
    SOURCE_ORDER,
    TARGET_TABLES,
    canonical_json_bytes,
    document_digest,
    portfolio_plan_digest,
    require_run_id,
    stable_id,
)


MAX_MODEL_RESPONSE_BYTES = 256 * 1024
ARTIFACT_KEYS = frozenset({"source_manifest", "record_batch", "redaction_report"})
FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "raw",
        "payload",
        "bytes",
        "pii",
        "secret",
        "credential",
        "code",
        "command",
        "script",
        "expression",
    }
)
EXECUTABLE_OUTPUT_KEYS = frozenset(
    {"code", "command", "script", "expression", "eval", "exec"}
)
CLOUD_OPERATIONS = frozenset({"rename", "cast", "drop"})

SYSTEM_INSTRUCTIONS = """You compile three already decoded and tokenized legacy
record batches into declarative TransformPlan drafts. Return JSON only with
exactly one plans array and one draft for jde, maxdb, and btrieve. Each draft
contains only sourceId, operations, and outputFields. Use only the operations
defined by the supplied contract. Never emit code, commands, scripts, SQL,
expressions, callbacks, tools, or execution claims. You plan; you do not run.
The inputs are sanitized and must never be described as raw or unredacted."""

MODEL_DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["plans"],
    "properties": {
        "plans": {
            "type": "array",
            "minItems": len(SOURCE_ORDER),
            "maxItems": len(SOURCE_ORDER),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sourceId", "operations", "outputFields"],
                "properties": {
                    "sourceId": {"type": "string", "enum": list(SOURCE_ORDER)},
                    "operations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "oneOf": [
                                {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["operation", "from", "to"],
                                    "properties": {
                                        "operation": {"const": "rename"},
                                        "from": {"type": "string"},
                                        "to": {"type": "string"},
                                    },
                                },
                                {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [
                                        "operation",
                                        "field",
                                        "targetType",
                                        "invalidPolicy",
                                    ],
                                    "properties": {
                                        "operation": {"const": "cast"},
                                        "field": {"type": "string"},
                                        "targetType": {
                                            "type": "string",
                                            "enum": [
                                                "string",
                                                "integer",
                                                "decimal",
                                                "date",
                                                "timestamp",
                                                "boolean",
                                                "bytes",
                                            ],
                                        },
                                        "invalidPolicy": {
                                            "type": "string",
                                            "enum": ["reject", "null"],
                                        },
                                    },
                                },
                                {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["operation", "field"],
                                    "properties": {
                                        "operation": {"const": "drop"},
                                        "field": {"type": "string"},
                                    },
                                },
                            ]
                        },
                    },
                    "outputFields": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "type", "nullable"],
                            "properties": {
                                "name": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "string",
                                        "integer",
                                        "decimal",
                                        "date",
                                        "timestamp",
                                        "boolean",
                                        "bytes",
                                    ],
                                },
                                "nullable": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
        }
    },
}


class PlanCompilationError(RuntimeError):
    """Safe compiler failure that never includes artifact or model values."""


ModelResponse = Union[str, Mapping[str, object]]
ModelCall = Callable[[Mapping[str, object]], Awaitable[ModelResponse]]


@dataclasses.dataclass(frozen=True)
class PortfolioPlan:
    plans: tuple[Mapping[str, object], ...] = dataclasses.field(repr=False)
    portfolio_digest: str
    model: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "plans", tuple(_deep_freeze(plan) for plan in self.plans))

    def as_documents(self) -> tuple[dict[str, object], ...]:
        """Return detached JSON-compatible copies for validation or persistence."""

        return tuple(_deep_thaw(plan) for plan in self.plans)


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(child) for key, child in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(child) for child in value)
    return value


def _deep_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(child) for child in value]
    return value


def _walk_keys(value: object, forbidden: frozenset[str], message: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key.casefold() in forbidden:
                raise PlanCompilationError(message)
            _walk_keys(child, forbidden, message)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _walk_keys(child, forbidden, message)


def _schema_validators() -> dict[str, Draft202012Validator]:
    schema_dir = Path(__file__).resolve().parents[1] / "contracts" / "schemas"
    names = {
        "transform_plan": "transform-plan.schema.json",
        "source_manifest": "source-manifest.schema.json",
        "record_batch": "record-batch.schema.json",
        "redaction_report": "redaction-report.schema.json",
        "common": "common.schema.json",
    }
    try:
        schemas = {
            name: json.loads((schema_dir / filename).read_text(encoding="utf-8"))
            for name, filename in names.items()
        }
        registry = Registry().with_resources(
            [
                (schema["$id"], Resource.from_contents(schema))
                for schema in schemas.values()
            ]
        )
        validators = {}
        for name, schema in schemas.items():
            Draft202012Validator.check_schema(schema)
            validators[name] = Draft202012Validator(schema, registry=registry)
        return validators
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        SchemaError,
        json.JSONDecodeError,
    ):
        raise PlanCompilationError("planning contracts are unavailable") from None


def _manifest_digest(manifest: Mapping[str, object]) -> str:
    return document_digest(manifest)


def _batch_field_names(batch: Mapping[str, object]) -> set[str]:
    records = batch.get("records")
    if not isinstance(records, list) or not records:
        raise PlanCompilationError("record batch structure is invalid")

    expected: set[str] | None = None
    record_ids: set[str] = set()
    for expected_ordinal, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise PlanCompilationError("record batch structure is invalid")
        record_id = record.get("recordId")
        if (
            record.get("ordinal") != expected_ordinal
            or not isinstance(record_id, str)
            or record_id in record_ids
        ):
            raise PlanCompilationError("record batch identity is invalid")
        record_ids.add(record_id)

        values = record.get("values")
        if not isinstance(values, list) or not values:
            raise PlanCompilationError("record batch structure is invalid")
        names: set[str] = set()
        for value in values:
            if not isinstance(value, Mapping):
                raise PlanCompilationError("record batch structure is invalid")
            name = value.get("field")
            if not isinstance(name, str) or name in names:
                raise PlanCompilationError("record batch fields are invalid")
            names.add(name)
        if expected is None:
            expected = names
        elif names != expected:
            raise PlanCompilationError("record batch fields are inconsistent")

    if batch.get("recordCount") != len(records) or expected is None:
        raise PlanCompilationError("record batch count is invalid")
    return expected


def _validate_cloud_draft(
    draft: Mapping[str, object], batch: Mapping[str, object]
) -> None:
    """Reject plans that the closed cloud interpreter cannot apply."""

    fields = _batch_field_names(batch)
    operations = draft.get("operations")
    output_fields = draft.get("outputFields")
    if not isinstance(operations, list) or not operations:
        raise PlanCompilationError("Gemini plan operations are invalid")
    if not isinstance(output_fields, list) or not output_fields:
        raise PlanCompilationError("Gemini output fields are invalid")

    for operation in operations:
        if not isinstance(operation, Mapping):
            raise PlanCompilationError("Gemini plan operation is invalid")
        operation_name = operation.get("operation")
        if operation_name not in CLOUD_OPERATIONS:
            raise PlanCompilationError("Gemini plan uses a non-cloud operation")
        if operation_name == "rename":
            old_name = operation.get("from")
            new_name = operation.get("to")
            if (
                not isinstance(old_name, str)
                or not isinstance(new_name, str)
                or old_name == new_name
                or old_name not in fields
                or new_name in fields
            ):
                raise PlanCompilationError("Gemini rename operation is invalid")
            fields.remove(old_name)
            fields.add(new_name)
        elif operation_name == "cast":
            field = operation.get("field")
            if not isinstance(field, str) or field not in fields:
                raise PlanCompilationError("Gemini cast operation is invalid")
        else:
            field = operation.get("field")
            if not isinstance(field, str) or field not in fields:
                raise PlanCompilationError("Gemini drop operation is invalid")
            fields.remove(field)

    declared: set[str] = set()
    for output_field in output_fields:
        if not isinstance(output_field, Mapping):
            raise PlanCompilationError("Gemini output fields are invalid")
        name = output_field.get("name")
        if not isinstance(name, str) or name in declared:
            raise PlanCompilationError("Gemini output fields are invalid")
        declared.add(name)
    if declared != fields:
        raise PlanCompilationError("Gemini output fields do not match operations")


def _preflight_artifacts(
    run_id: str,
    artifacts_by_source: Mapping[str, Mapping[str, object]],
    validators: Mapping[str, Draft202012Validator],
) -> None:
    if not isinstance(artifacts_by_source, Mapping):
        raise PlanCompilationError("artifacts must be a source mapping")
    if set(artifacts_by_source) != set(SOURCE_ORDER):
        raise PlanCompilationError("artifacts must contain exactly three sources")

    for source_id in SOURCE_ORDER:
        artifacts = artifacts_by_source[source_id]
        if not isinstance(artifacts, Mapping) or set(artifacts) != ARTIFACT_KEYS:
            raise PlanCompilationError("source artifacts do not match the handoff contract")
        manifest = artifacts["source_manifest"]
        batch = artifacts["record_batch"]
        report = artifacts["redaction_report"]
        if not all(isinstance(item, Mapping) for item in (manifest, batch, report)):
            raise PlanCompilationError("source artifacts must be mappings")
        if (
            not validators["source_manifest"].is_valid(manifest)
            or not validators["record_batch"].is_valid(batch)
            or not validators["redaction_report"].is_valid(report)
        ):
            raise PlanCompilationError("source artifact failed schema validation")
        if any(item.get("runId") != run_id for item in (manifest, batch, report)):
            raise PlanCompilationError("artifact run binding does not match")
        if any(item.get("sourceId") != source_id for item in (manifest, batch, report)):
            raise PlanCompilationError("artifact source binding does not match")

        digest = _manifest_digest(manifest)
        if batch.get("sourceManifestDigest") != digest or report.get(
            "sourceManifestDigest"
        ) != digest:
            raise PlanCompilationError("artifact manifest reference does not match")
        if report.get("reportDigest") != document_digest(
            report, omit=("reportDigest",)
        ):
            raise PlanCompilationError("redaction report digest does not match")
        record_sets = manifest.get("recordSets")
        if not isinstance(record_sets, list) or len(record_sets) != 1:
            raise PlanCompilationError("manifest must contain one record set")
        record_set = record_sets[0]
        if not isinstance(record_set, Mapping):
            raise PlanCompilationError("manifest record set is invalid")
        if (
            record_set.get("name") != batch.get("recordSet")
            or record_set.get("recordCount") != batch.get("recordCount")
        ):
            raise PlanCompilationError("artifact record counts do not match")
        _batch_field_names(batch)

        deterministic = report.get("deterministicCheck")
        local_gemma = report.get("localGemmaCheck")
        if (
            report.get("status") != "passed"
            or report.get("failClosed") is not True
            or report.get("unresolvedFindingCount") != 0
            or not isinstance(deterministic, Mapping)
            or deterministic.get("status") != "passed"
            or not isinstance(local_gemma, Mapping)
            or local_gemma.get("status") != "passed"
            or local_gemma.get("findingCount") != 0
        ):
            raise PlanCompilationError("redaction report is not safe for planning")

    _walk_keys(
        artifacts_by_source,
        FORBIDDEN_INPUT_KEYS,
        "artifact contains a forbidden key",
    )


class GeminiPlanCompiler:
    def __init__(
        self,
        model_call: ModelCall,
        model_name: str,
        dataset: str = "legacy_migration",
    ) -> None:
        if not callable(model_call):
            raise ValueError("model_call must be callable")
        if not model_name.startswith("gemini-"):
            raise ValueError("model_name must identify a Gemini model")
        self._model_call = model_call
        self.model_name = model_name
        self.dataset = dataset
        self._validators = _schema_validators()

    async def compile(
        self,
        run_id: str,
        artifacts_by_source: Mapping[str, Mapping[str, object]],
    ) -> PortfolioPlan:
        try:
            require_run_id(run_id)
            _preflight_artifacts(run_id, artifacts_by_source, self._validators)
        except ValueError:
            raise PlanCompilationError("planner preflight failed") from None

        request = {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "instructions": SYSTEM_INSTRUCTIONS,
            "sources": [
                {
                    "sourceId": source_id,
                    **copy.deepcopy(dict(artifacts_by_source[source_id])),
                }
                for source_id in SOURCE_ORDER
            ],
        }
        try:
            response = await self._model_call(request)
        except Exception:
            raise PlanCompilationError("Gemini planning call failed") from None

        if isinstance(response, str):
            if len(response.encode("utf-8")) > MAX_MODEL_RESPONSE_BYTES:
                raise PlanCompilationError("Gemini response exceeds the size limit")
            try:
                draft = json.loads(response)
            except json.JSONDecodeError:
                raise PlanCompilationError("Gemini returned invalid JSON") from None
        elif isinstance(response, Mapping):
            draft = copy.deepcopy(dict(response))
            try:
                if len(canonical_json_bytes(draft)) > MAX_MODEL_RESPONSE_BYTES:
                    raise PlanCompilationError("Gemini response exceeds the size limit")
            except (TypeError, ValueError):
                raise PlanCompilationError("Gemini returned a non-JSON value") from None
        else:
            raise PlanCompilationError("Gemini returned an unsupported response")

        if not isinstance(draft, dict) or set(draft) != {"plans"}:
            raise PlanCompilationError("Gemini response has unknown fields")
        drafts = draft["plans"]
        if not isinstance(drafts, list) or len(drafts) != len(SOURCE_ORDER):
            raise PlanCompilationError("Gemini must return exactly three plans")

        by_source = {}
        for item in drafts:
            if not isinstance(item, dict) or set(item) != {
                "sourceId",
                "operations",
                "outputFields",
            }:
                raise PlanCompilationError("Gemini plan draft has unknown fields")
            source_id = item.get("sourceId")
            if source_id not in SOURCE_ORDER or source_id in by_source:
                raise PlanCompilationError("Gemini plan sources are invalid")
            _walk_keys(
                item,
                EXECUTABLE_OUTPUT_KEYS,
                "Gemini plan contains executable content",
            )
            _validate_cloud_draft(
                item, artifacts_by_source[str(source_id)]["record_batch"]
            )
            by_source[source_id] = item
        if set(by_source) != set(SOURCE_ORDER):
            raise PlanCompilationError("Gemini must plan every source exactly once")

        plans = []
        for source_id in SOURCE_ORDER:
            item = by_source[source_id]
            manifest = artifacts_by_source[source_id]["source_manifest"]
            plan = {
                "schemaVersion": SCHEMA_VERSION,
                "planId": stable_id("plan_", run_id, source_id),
                "runId": run_id,
                "sourceId": source_id,
                "sourceManifestDigest": _manifest_digest(manifest),
                "target": {
                    "dataset": self.dataset,
                    "table": TARGET_TABLES[source_id],
                },
                "operations": copy.deepcopy(item["operations"]),
                "outputFields": copy.deepcopy(item["outputFields"]),
            }
            plan["planDigest"] = document_digest(plan, omit=("planDigest",))
            if not self._validators["transform_plan"].is_valid(plan):
                raise PlanCompilationError("Gemini plan failed schema validation")
            plans.append(plan)

        portfolio_digest = portfolio_plan_digest(plans)
        return PortfolioPlan(tuple(plans), portfolio_digest, self.model_name)


def antigravity_model_call_factory(
    *,
    model_name: Optional[str] = None,
    location: Optional[str] = None,
) -> ModelCall:
    """Create a lazy Vertex/Antigravity call; no client is built at import time."""

    selected_model = model_name or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    selected_location = location or os.environ.get("VERTEX_LOCATION", "us-central1")

    async def call(request: Mapping[str, object]) -> str:
        from google.antigravity import Agent, LocalAgentConfig

        config = LocalAgentConfig(
            model=selected_model,
            vertex=True,
            location=selected_location,
            tools=[],
            system_instructions=SYSTEM_INSTRUCTIONS,
            response_schema=MODEL_DRAFT_SCHEMA,
        )
        async with Agent(config=config) as agent:
            response = await agent.chat(
                json.dumps(request, ensure_ascii=False, sort_keys=True)
            )
            return await response.text()

    return call
