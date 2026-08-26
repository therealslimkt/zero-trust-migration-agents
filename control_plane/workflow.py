"""Fail-closed composition of planning, approval, and trusted execution.

This module has no persistence or cloud side effects.  It snapshots the
sanitized edge handoffs and declarative plans in canonical JSON, then passes
detached copies to the closed trusted interpreter only after the complete
portfolio and its approval have been revalidated.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from types import MappingProxyType

import trusted_runtime
from control_plane.artifacts import EdgeArtifacts
from control_plane.canonical import (
    SCHEMA_VERSION,
    SOURCE_ORDER,
    canonical_json_bytes,
    document_digest,
    portfolio_plan_digest,
    require_digest,
    require_run_id,
)
from control_plane.gemini_planner import (
    GeminiPlanCompiler,
    PlanCompilationError,
)
from ztm_security.approval import (
    ApprovalRecord,
    PolicyDenied,
    authorize_run,
    check_non_overridable,
)


class PortfolioWorkflowError(ValueError):
    """A safe workflow rejection whose message never contains document data."""


@dataclasses.dataclass(frozen=True)
class PreparedPortfolio:
    """An immutable canonical snapshot forming the portfolio approval anchor."""

    _snapshot_json: bytes = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        if type(self._snapshot_json) is not bytes:
            raise PortfolioWorkflowError("prepared portfolio is invalid")

    def as_document(self) -> dict[str, object]:
        """Return a detached JSON document; mutations cannot alter this snapshot."""

        return json.loads(self._snapshot_json)

    @property
    def run_id(self) -> str:
        return str(self.as_document()["runId"])

    @property
    def portfolio_digest(self) -> str:
        return str(self.as_document()["portfolioDigest"])

    @property
    def model(self) -> str:
        return str(self.as_document()["model"])

    @property
    def plans(self) -> tuple[dict[str, object], ...]:
        document = self.as_document()
        return tuple(source["plan"] for source in document["sources"])  # type: ignore[index,return-value]

    @property
    def artifacts_by_source(self) -> dict[str, dict[str, dict[str, object]]]:
        document = self.as_document()
        result: dict[str, dict[str, dict[str, object]]] = {}
        for source in document["sources"]:  # type: ignore[union-attr]
            source_id = str(source["sourceId"])
            result[source_id] = {
                "source_manifest": source["sourceManifest"],
                "record_batch": source["recordBatch"],
                "redaction_report": source["redactionReport"],
            }
        return result


@dataclasses.dataclass(frozen=True)
class SourceReconciliation:
    """Immutable protected output and reconciliation evidence for one source."""

    source_id: str
    target: Mapping[str, str]
    row_count: int
    output_digest: str
    rows: tuple[Mapping[str, object], ...] = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _deep_freeze(dict(self.target)))
        object.__setattr__(self, "rows", _deep_freeze(self.rows))

    @property
    def record_count(self) -> int:
        """Compatibility name used by the single-plan trusted interpreter."""

        return self.row_count


@dataclasses.dataclass(frozen=True)
class PortfolioExecutionResult:
    """All-or-nothing in-memory result in canonical source order."""

    run_id: str
    portfolio_digest: str
    reconciliations: tuple[SourceReconciliation, ...]

    @property
    def results(self) -> tuple[SourceReconciliation, ...]:
        return self.reconciliations

    @property
    def sources(self) -> tuple[SourceReconciliation, ...]:
        return self.reconciliations


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(child) for key, child in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(child) for child in value)
    return value


def _canonical_copy(value: object) -> object:
    return json.loads(canonical_json_bytes(value))


def _reject(message: str) -> None:
    raise PortfolioWorkflowError(message)


def _validate_source_documents(
    source_id: str,
    artifacts: Mapping[str, object],
    run_id: str | None,
) -> str:
    if set(artifacts) != {
        "source_manifest",
        "record_batch",
        "redaction_report",
    }:
        _reject("portfolio artifacts are invalid")
    manifest = artifacts["source_manifest"]
    batch = artifacts["record_batch"]
    report = artifacts["redaction_report"]
    if not all(type(document) is dict for document in (manifest, batch, report)):
        _reject("portfolio artifacts are invalid")

    documents = (manifest, batch, report)
    source_run_id = manifest.get("runId")  # type: ignore[union-attr]
    try:
        require_run_id(source_run_id)
    except (TypeError, ValueError):
        _reject("portfolio artifacts are invalid")
    if run_id is not None and source_run_id != run_id:
        _reject("portfolio artifacts are invalid")
    if any(document.get("runId") != source_run_id for document in documents):  # type: ignore[union-attr]
        _reject("portfolio artifacts are invalid")
    if any(document.get("sourceId") != source_id for document in documents):  # type: ignore[union-attr]
        _reject("portfolio artifacts are invalid")

    manifest_digest = document_digest(manifest)  # type: ignore[arg-type]
    if (
        batch.get("sourceManifestDigest") != manifest_digest  # type: ignore[union-attr]
        or report.get("sourceManifestDigest") != manifest_digest  # type: ignore[union-attr]
    ):
        _reject("portfolio artifacts are invalid")
    if report.get("reportDigest") != document_digest(  # type: ignore[union-attr,arg-type]
        report, omit=("reportDigest",)
    ):
        _reject("portfolio artifacts are invalid")

    record_sets = manifest.get("recordSets")  # type: ignore[union-attr]
    records = batch.get("records")  # type: ignore[union-attr]
    if (
        not isinstance(record_sets, list)
        or len(record_sets) != 1
        or type(record_sets[0]) is not dict
        or not isinstance(records, list)
        or batch.get("recordCount") != len(records)  # type: ignore[union-attr]
    ):
        _reject("portfolio artifacts are invalid")
    record_set = record_sets[0]
    if (
        record_set.get("name") != batch.get("recordSet")  # type: ignore[union-attr]
        or record_set.get("recordCount") != batch.get("recordCount")  # type: ignore[union-attr]
        or record_set.get("schemaDigest") != batch.get("schemaDigest")  # type: ignore[union-attr]
    ):
        _reject("portfolio artifacts are invalid")
    if (
        report.get("status") != "passed"  # type: ignore[union-attr]
        or report.get("failClosed") is not True  # type: ignore[union-attr]
        or report.get("unresolvedFindingCount") != 0  # type: ignore[union-attr]
    ):
        _reject("portfolio artifacts are invalid")
    return str(source_run_id)


def _snapshot_artifacts(
    artifacts_by_source: Mapping[str, EdgeArtifacts],
) -> tuple[str, dict[str, dict[str, object]]]:
    if not isinstance(artifacts_by_source, Mapping):
        _reject("portfolio artifacts are invalid")
    if set(artifacts_by_source) != set(SOURCE_ORDER):
        _reject("portfolio artifacts are invalid")

    snapshot: dict[str, dict[str, object]] = {}
    run_id: str | None = None
    for source_id in SOURCE_ORDER:
        edge_artifacts = artifacts_by_source[source_id]
        if not isinstance(edge_artifacts, EdgeArtifacts):
            _reject("portfolio artifacts are invalid")
        copied = _canonical_copy(edge_artifacts.as_mapping())
        if type(copied) is not dict:
            _reject("portfolio artifacts are invalid")
        run_id = _validate_source_documents(source_id, copied, run_id)
        snapshot[source_id] = copied
    if run_id is None:  # SOURCE_ORDER is a repository invariant.
        _reject("portfolio artifacts are invalid")
    return run_id, snapshot


def _validate_plans(
    plans: object,
    artifacts_by_source: Mapping[str, Mapping[str, object]],
    run_id: str,
) -> tuple[list[dict[str, object]], str]:
    if not isinstance(plans, (list, tuple)) or len(plans) != len(SOURCE_ORDER):
        _reject("compiled portfolio is invalid")

    by_source: dict[str, dict[str, object]] = {}
    for raw_plan in plans:
        copied = _canonical_copy(raw_plan)
        if type(copied) is not dict:
            _reject("compiled portfolio is invalid")
        source_id = copied.get("sourceId")
        if source_id not in SOURCE_ORDER or source_id in by_source:
            _reject("compiled portfolio is invalid")
        if copied.get("runId") != run_id:
            _reject("compiled portfolio is invalid")
        if copied.get("planDigest") != document_digest(
            copied, omit=("planDigest",)
        ):
            _reject("compiled portfolio is invalid")

        artifacts = artifacts_by_source[str(source_id)]
        manifest = artifacts["source_manifest"]
        batch = artifacts["record_batch"]
        manifest_digest = document_digest(manifest)  # type: ignore[arg-type]
        if (
            copied.get("sourceManifestDigest") != manifest_digest
            or batch.get("runId") != copied.get("runId")  # type: ignore[union-attr]
            or batch.get("sourceId") != copied.get("sourceId")  # type: ignore[union-attr]
            or batch.get("sourceManifestDigest")  # type: ignore[union-attr]
            != copied.get("sourceManifestDigest")
        ):
            _reject("compiled portfolio is invalid")
        by_source[str(source_id)] = copied

    if set(by_source) != set(SOURCE_ORDER):
        _reject("compiled portfolio is invalid")
    ordered = [by_source[source_id] for source_id in SOURCE_ORDER]
    try:
        digest = portfolio_plan_digest(ordered)
    except (TypeError, ValueError):
        _reject("compiled portfolio is invalid")
    return ordered, digest


async def prepare_portfolio(
    *,
    artifacts_by_source: Mapping[str, EdgeArtifacts],
    compiler: GeminiPlanCompiler,
) -> PreparedPortfolio:
    """Compile and snapshot one complete three-source portfolio exactly once."""

    try:
        run_id, artifacts = _snapshot_artifacts(artifacts_by_source)
        compiler_input = _canonical_copy(artifacts)
        compiled = await compiler.compile(run_id, compiler_input)  # type: ignore[arg-type]
        plans, recomputed_digest = _validate_plans(
            compiled.as_documents(), artifacts, run_id
        )
        if compiled.portfolio_digest != recomputed_digest:
            _reject("compiled portfolio is invalid")
        if not isinstance(compiled.model, str) or not compiled.model:
            _reject("compiled portfolio is invalid")

        document = {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "portfolioDigest": recomputed_digest,
            "model": compiled.model,
            "sources": [
                {
                    "sourceId": source_id,
                    "sourceManifest": artifacts[source_id]["source_manifest"],
                    "recordBatch": artifacts[source_id]["record_batch"],
                    "redactionReport": artifacts[source_id]["redaction_report"],
                    "plan": plan,
                }
                for source_id, plan in zip(SOURCE_ORDER, plans)
            ],
        }
        return PreparedPortfolio(canonical_json_bytes(document))
    except PortfolioWorkflowError:
        raise
    except PlanCompilationError as exc:
        # Only the exact repository-owned compiler is permitted to surface its
        # fixed diagnostic vocabulary. Injected test compilers remain opaque.
        if type(compiler) is GeminiPlanCompiler:
            raise PortfolioWorkflowError(
                f"portfolio planning failed: {exc}"
            ) from None
        raise PortfolioWorkflowError("portfolio preparation failed") from None
    except Exception:
        raise PortfolioWorkflowError("portfolio preparation failed") from None


def _decode_prepared(
    prepared: PreparedPortfolio,
) -> tuple[str, str, list[dict[str, object]]]:
    if not isinstance(prepared, PreparedPortfolio):
        _reject("prepared portfolio is invalid")
    try:
        document = json.loads(prepared._snapshot_json)
    except Exception:
        _reject("prepared portfolio is invalid")
    if type(document) is not dict or set(document) != {
        "schemaVersion",
        "runId",
        "portfolioDigest",
        "model",
        "sources",
    }:
        _reject("prepared portfolio is invalid")
    if document.get("schemaVersion") != SCHEMA_VERSION:
        _reject("prepared portfolio is invalid")
    run_id = document.get("runId")
    try:
        require_run_id(run_id)
        require_digest(document.get("portfolioDigest"))
    except (TypeError, ValueError):
        _reject("prepared portfolio is invalid")

    raw_sources = document.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != len(SOURCE_ORDER):
        _reject("prepared portfolio is invalid")
    artifacts: dict[str, dict[str, object]] = {}
    plans: list[dict[str, object]] = []
    for expected_source, source in zip(SOURCE_ORDER, raw_sources):
        if type(source) is not dict or set(source) != {
            "sourceId",
            "sourceManifest",
            "recordBatch",
            "redactionReport",
            "plan",
        }:
            _reject("prepared portfolio is invalid")
        if source.get("sourceId") != expected_source:
            _reject("prepared portfolio is invalid")
        source_artifacts = {
            "source_manifest": source["sourceManifest"],
            "record_batch": source["recordBatch"],
            "redaction_report": source["redactionReport"],
        }
        _validate_source_documents(expected_source, source_artifacts, str(run_id))
        artifacts[expected_source] = source_artifacts
        plan = source["plan"]
        if type(plan) is not dict:
            _reject("prepared portfolio is invalid")
        plans.append(plan)

    validated_plans, recomputed_digest = _validate_plans(
        plans, artifacts, str(run_id)
    )
    if recomputed_digest != document.get("portfolioDigest"):
        _reject("prepared portfolio is invalid")
    return str(run_id), recomputed_digest, [
        {
            "plan": plan,
            "record_batch": artifacts[source_id]["record_batch"],
        }
        for source_id, plan in zip(SOURCE_ORDER, validated_plans)
    ]


def _reconciliation(
    source_id: str,
    plan: Mapping[str, object],
    result: object,
) -> SourceReconciliation:
    result_source = getattr(result, "source_id")
    result_target = getattr(result, "target")
    rows = getattr(result, "rows")
    record_count = getattr(result, "record_count")
    output_digest = getattr(result, "output_digest")
    if (
        result_source != source_id
        or not isinstance(result_target, Mapping)
        or result_target != plan.get("target")
        or not isinstance(rows, tuple)
        or type(record_count) is not int
        or record_count != len(rows)
    ):
        _reject("portfolio execution failed")
    try:
        require_digest(output_digest)
    except (TypeError, ValueError):
        _reject("portfolio execution failed")
    return SourceReconciliation(
        source_id=source_id,
        target=result_target,
        row_count=record_count,
        output_digest=output_digest,
        rows=rows,
    )


def execute_portfolio(
    *,
    prepared: PreparedPortfolio,
    approval: ApprovalRecord,
    policy_categories,
) -> PortfolioExecutionResult:
    """Authorize and execute a complete prepared portfolio, or return nothing."""

    try:
        if isinstance(policy_categories, (str, bytes)):
            raise PolicyDenied("policy categories are invalid")
        normalized_categories = frozenset(policy_categories)
        check_non_overridable(normalized_categories)
    except (PolicyDenied, TypeError):
        raise PortfolioWorkflowError("portfolio policy was rejected") from None

    run_id, portfolio_digest, sources = _decode_prepared(prepared)
    try:
        if not isinstance(approval, ApprovalRecord):
            _reject("portfolio approval was rejected")
        authorize_run(
            approval,
            portfolio_digest,
            run_id,
            categories=normalized_categories,
        )
    except PortfolioWorkflowError:
        raise
    except Exception:
        raise PortfolioWorkflowError("portfolio approval was rejected") from None

    results: list[SourceReconciliation] = []
    try:
        for source_id, source in zip(SOURCE_ORDER, sources):
            plan = source["plan"]
            record_batch = source["record_batch"]
            execution = trusted_runtime.execute_plan(
                plan=plan,
                record_batch=record_batch,
                approval=approval,
                portfolio_digest=portfolio_digest,
                policy_categories=normalized_categories,
            )
            results.append(_reconciliation(source_id, plan, execution))
    except Exception:
        results.clear()
        raise PortfolioWorkflowError("portfolio execution failed") from None

    return PortfolioExecutionResult(
        run_id=run_id,
        portfolio_digest=portfolio_digest,
        reconciliations=tuple(results),
    )
