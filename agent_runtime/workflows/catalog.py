"""Exact-version ADK graph assembly for the catalog-first workflow."""

from __future__ import annotations

import dataclasses

from agent_runtime.adk_compat import installed_adk_version, require_python_312


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

    require_python_312()
    actual = installed_adk_version()
    if actual != "2.7.1":
        raise RuntimeError(f"google-adk version must be 2.7.1; found {actual}")
    from google.adk.workflow import DEFAULT_ROUTE, JoinNode, START, Workflow, node

    validate = node(nodes.validate_intent, name="validate_intent")
    metadata = node(nodes.metadata, name="catalog_metadata")
    vector = node(nodes.vector, name="catalog_vector")
    access = node(nodes.access, name="catalog_access")
    joined = JoinNode(name="catalog_join")
    router = node(nodes.route_catalog, name="route_catalog")
    existing = node(nodes.existing_asset, name="prepare_access_request")
    intake = node(nodes.needs_input, name="source_intake", rerun_on_resume=True)
    migrate = node(nodes.migrate, name="source_portfolio")
    failed = node(nodes.fail_closed, name="catalog_fail_closed")
    return Workflow(
        name="catalog_first",
        max_concurrency=4,
        edges=[
            (START, validate, (metadata, vector, access), joined, router),
            (
                router,
                {
                    "EXISTING_ASSET": existing,
                    "NEEDS_INPUT": intake,
                    "MIGRATE": migrate,
                    DEFAULT_ROUTE: failed,
                },
            ),
        ],
    )
