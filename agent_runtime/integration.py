"""Typed joins between the independent Milestone 2 orchestration patterns."""

from __future__ import annotations

from collections.abc import Mapping

from .adk_compat import load_adk_patterns
from .application import RuntimeApplication, RuntimeSettings, build_application
from .collaboration import AdkSchemaBundle, EligibleTeam, Portfolio, build_adk_atlas_team
from .dynamic import SourceInstance as DynamicSourceInstance
from .ports import ContractDocument, RuntimePorts
from .workflows import AdkCatalogNodes, build_catalog_workflow


class IntegrationViolation(ValueError):
    """Independent pattern outputs could not be joined exactly."""


def portfolio_to_dynamic_sources(
    portfolio: Portfolio,
    *,
    sanitized_requests: Mapping[str, ContractDocument],
) -> tuple[DynamicSourceInstance, ...]:
    """Convert the Atlas portfolio without dropping, adding, or reordering sources."""

    if not isinstance(portfolio, Portfolio):
        raise IntegrationViolation("integration_portfolio")
    if not isinstance(sanitized_requests, Mapping):
        raise IntegrationViolation("integration_requests")
    expected_ids = tuple(item.source_instance_id for item in portfolio.sources)
    if set(sanitized_requests) != set(expected_ids):
        raise IntegrationViolation("integration_request_coverage")
    if any(
        not isinstance(sanitized_requests[source_id], ContractDocument)
        for source_id in expected_ids
    ):
        raise IntegrationViolation("integration_request_document")
    return tuple(
        DynamicSourceInstance(
            instance_id=source.source_instance_id,
            source_id=source.family.value,
            request=sanitized_requests[source.source_instance_id],
        )
        for source in portfolio.sources
    )


def build_atlas_team(
    *,
    team: EligibleTeam,
    schemas: AdkSchemaBundle,
    model: object,
) -> object:
    """Version-gate the public ADK Agent constructor before team assembly."""

    adk = load_adk_patterns()
    return build_adk_atlas_team(
        agent_constructor=adk.Agent,
        team=team,
        schemas=schemas,
        model=model,
    )


def build_fleet_application(
    *,
    settings: RuntimeSettings,
    ports: RuntimePorts,
    catalog_nodes: AdkCatalogNodes,
) -> RuntimeApplication:
    """Assemble the pinned ADK App around the catalog-first fixed graph."""

    if not isinstance(catalog_nodes, AdkCatalogNodes):
        raise IntegrationViolation("integration_catalog_nodes")
    return build_application(
        settings=settings,
        ports=ports,
        root_factory=lambda _context: build_catalog_workflow(catalog_nodes),
    )
