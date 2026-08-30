"""Exhaustive zero-model routing functions."""

from __future__ import annotations

from .model import CatalogProbe, CatalogProbeKind, CatalogRoute, PlanRoute, PlanRouteInput


_PROBE_KINDS = frozenset(CatalogProbeKind)


def route_catalog(probes: tuple[CatalogProbe, ...]) -> CatalogRoute:
    """Select a named catalog edge; malformed/inconsistent facts fail closed."""

    if len(probes) != 3 or {probe.kind for probe in probes} != _PROBE_KINDS:
        return CatalogRoute.FAIL_CLOSED
    if any(not probe.trustworthy for probe in probes):
        return CatalogRoute.FAIL_CLOSED
    if any(probe.missing_input for probe in probes):
        return CatalogRoute.NEEDS_INPUT
    migration_values = {probe.migration_requested for probe in probes}
    if len(migration_values) != 1:
        return CatalogRoute.FAIL_CLOSED
    if any(probe.candidate_count > 0 for probe in probes):
        return CatalogRoute.EXISTING_ASSET
    if migration_values == {True}:
        return CatalogRoute.MIGRATE
    return CatalogRoute.FAIL_CLOSED


def route_plan(value: PlanRouteInput, *, repair_count: int) -> PlanRoute:
    """Route a plan with an absolute maximum of three research repairs."""

    if type(repair_count) is not int or not 0 <= repair_count <= 3:
        return PlanRoute.FAIL_CLOSED
    if not value.trustworthy:
        return PlanRoute.FAIL_CLOSED
    selected = sum(
        (value.needs_research, value.needs_input, value.policy_rejected, value.ready)
    )
    if selected != 1:
        return PlanRoute.FAIL_CLOSED
    if value.needs_research:
        return PlanRoute.NEEDS_RESEARCH if repair_count < 3 else PlanRoute.REJECTED
    if value.needs_input:
        return PlanRoute.NEEDS_INPUT
    if value.policy_rejected:
        return PlanRoute.REJECTED
    return PlanRoute.READY
