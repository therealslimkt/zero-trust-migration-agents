"""Exact-version ADK graph assembly for the catalog-first workflow."""

from __future__ import annotations

import dataclasses

from agent_runtime.adk_compat import load_adk_patterns
from agent_runtime.graph import CatalogRoute


@dataclasses.dataclass(frozen=True)
class AdkCatalogNodes:
    """Caller-owned typed callables/nodes; this factory grants no authority."""

    validate_intent: object
    metadata: object
    vector: object
    access: object
    route_catalog: object
    existing_asset: object
    needs_input: object
    migrate: object
    fail_closed: object


def build_catalog_workflow(nodes: AdkCatalogNodes) -> object:
    """Build a bounded ADK 2.7.1 Workflow using only verified public exports.

    The explicit default edge is security-significant: an unrecognized route
    reaches ``fail_closed`` instead of silently terminating a branch.
    """

    adk = load_adk_patterns()

    validate = adk.node(nodes.validate_intent, name="validate_intent")
    metadata = adk.node(nodes.metadata, name="catalog_metadata")
    vector = adk.node(nodes.vector, name="catalog_vector")
    access = adk.node(nodes.access, name="catalog_access")
    joined = adk.JoinNode(name="catalog_join")
    router = adk.node(nodes.route_catalog, name="route_catalog")
    existing = adk.node(nodes.existing_asset, name="prepare_access_request")
    intake = adk.node(nodes.needs_input, name="source_intake", rerun_on_resume=True)
    migrate = adk.node(nodes.migrate, name="source_portfolio")
    failed = adk.node(nodes.fail_closed, name="catalog_fail_closed")
    return adk.Workflow(
        name="catalog_first",
        max_concurrency=4,
        edges=[
            (adk.START, validate, (metadata, vector, access), joined, router),
            (
                router,
                {
                    CatalogRoute.EXISTING_ASSET.value: existing,
                    CatalogRoute.NEEDS_INPUT.value: intake,
                    CatalogRoute.MIGRATE.value: migrate,
                    adk.DEFAULT_ROUTE: failed,
                },
            ),
        ],
    )
