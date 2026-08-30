from __future__ import annotations

import importlib.metadata
import sys
from unittest import mock

import pytest

from agent_runtime.application import RuntimeSettings
from agent_runtime.collaboration import Portfolio, SourceFamily
from agent_runtime.collaboration import SourceInstance as CollaborativeSource
from agent_runtime.dynamic import SourceInstance as DynamicSource
from agent_runtime.integration import (
    IntegrationViolation,
    build_fleet_application,
    portfolio_to_dynamic_sources,
)
from agent_runtime.ports import ContractDocument
from agent_runtime.workflows import AdkCatalogNodes

from .fakes import runtime_port_fakes


def portfolio() -> Portfolio:
    return Portfolio(
        run_id="run_ENTERPRISE01",
        session_id="ses_ENTERPRISE01",
        objective="Migrate selected sources",
        sources=(
            CollaborativeSource("jde_primary", SourceFamily.JDE),
            CollaborativeSource("sap_primary", SourceFamily.SAP),
        ),
    )


def test_portfolio_join_is_exact_ordered_and_closed():
    documents = {
        "sap_primary": ContractDocument("ztm.sanitized.source.v2", {"source": "sap"}),
        "jde_primary": ContractDocument("ztm.sanitized.source.v2", {"source": "jde"}),
    }
    converted = portfolio_to_dynamic_sources(
        portfolio(), sanitized_requests=documents
    )
    assert all(isinstance(item, DynamicSource) for item in converted)
    assert [item.instance_id for item in converted] == ["jde_primary", "sap_primary"]
    assert [item.source_id for item in converted] == [
        "jde_e1_ibmi",
        "sap_ecc_maxdb",
    ]
    with pytest.raises(IntegrationViolation, match="integration_request_coverage"):
        portfolio_to_dynamic_sources(
            portfolio(), sanitized_requests={"jde_primary": documents["jde_primary"]}
        )


def test_fleet_application_joins_existing_composition_and_catalog_factory():
    passthrough = lambda node_input=None: node_input
    nodes = AdkCatalogNodes(*([passthrough] * 9))
    root = object()
    application = object()
    with mock.patch(
        "agent_runtime.integration.build_catalog_workflow", return_value=root
    ) as workflow_builder, mock.patch(
        "agent_runtime.integration.build_application", return_value=application
    ) as app_builder:
        result = build_fleet_application(
            settings=RuntimeSettings(app_name="fleet_test", environment="test"),
            ports=runtime_port_fakes(),
            catalog_nodes=nodes,
        )
        assert result is application
        root_factory = app_builder.call_args.kwargs["root_factory"]
        assert root_factory(object()) is root
        workflow_builder.assert_called_once_with(nodes)


def _has_pinned_adk() -> bool:
    try:
        return importlib.metadata.version("google-adk") == "2.7.1"
    except importlib.metadata.PackageNotFoundError:
        return False


@pytest.mark.skipif(
    sys.version_info[:2] != (3, 12) or not _has_pinned_adk(),
    reason="pinned ADK smoke test requires the isolated Python 3.12 runtime",
)
def test_fleet_application_constructs_real_pinned_adk_app():
    def passthrough(node_input=None):
        return node_input

    application = build_fleet_application(
        settings=RuntimeSettings(app_name="fleet_integration", environment="test"),
        ports=runtime_port_fakes(),
        catalog_nodes=AdkCatalogNodes(*([passthrough] * 9)),
    )
    assert application.adk_app.name == "fleet_integration"
    assert application.adk_app.root_agent.name == "catalog_first"
    assert application.adk_app.root_agent.max_concurrency == 4
