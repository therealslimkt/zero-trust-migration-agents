from __future__ import annotations

import pytest

from agent_runtime.graph import (
    CatalogProbe,
    CatalogProbeKind,
    CatalogRoute,
    PlanRoute,
    PlanRouteInput,
    route_catalog,
    route_plan,
)


def probes(**changes):
    values = {
        kind: CatalogProbe(kind=kind, **changes) for kind in CatalogProbeKind
    }
    return tuple(values[kind] for kind in CatalogProbeKind)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({"candidate_count": 1}, CatalogRoute.EXISTING_ASSET),
        ({"missing_input": True}, CatalogRoute.NEEDS_INPUT),
        ({}, CatalogRoute.MIGRATE),
        ({"trustworthy": False}, CatalogRoute.FAIL_CLOSED),
        ({"migration_requested": False}, CatalogRoute.FAIL_CLOSED),
    ],
)
def test_catalog_router_has_an_explicit_result_for_every_fact_class(facts, expected):
    assert route_catalog(probes(**facts)) is expected


def test_catalog_router_fails_closed_for_incomplete_or_inconsistent_join():
    complete = probes()
    assert route_catalog(complete[:2]) is CatalogRoute.FAIL_CLOSED
    inconsistent = list(complete)
    inconsistent[0] = CatalogProbe(
        kind=CatalogProbeKind.METADATA, migration_requested=False
    )
    assert route_catalog(tuple(inconsistent)) is CatalogRoute.FAIL_CLOSED


@pytest.mark.parametrize(
    ("value", "repairs", "expected"),
    [
        (PlanRouteInput(needs_research=True), 0, PlanRoute.NEEDS_RESEARCH),
        (PlanRouteInput(needs_research=True), 2, PlanRoute.NEEDS_RESEARCH),
        (PlanRouteInput(needs_research=True), 3, PlanRoute.REJECTED),
        (PlanRouteInput(needs_input=True), 0, PlanRoute.NEEDS_INPUT),
        (PlanRouteInput(policy_rejected=True), 0, PlanRoute.REJECTED),
        (PlanRouteInput(ready=True), 0, PlanRoute.READY),
        (PlanRouteInput(), 0, PlanRoute.FAIL_CLOSED),
        (PlanRouteInput(ready=True, needs_input=True), 0, PlanRoute.FAIL_CLOSED),
        (PlanRouteInput(ready=True, trustworthy=False), 0, PlanRoute.FAIL_CLOSED),
        (PlanRouteInput(ready=True), 4, PlanRoute.FAIL_CLOSED),
    ],
)
def test_plan_router_is_exhaustive_and_enforces_three_repairs(value, repairs, expected):
    assert route_plan(value, repair_count=repairs) is expected
