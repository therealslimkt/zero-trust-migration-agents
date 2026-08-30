from __future__ import annotations

import importlib.metadata
import sys

import pytest

from agent_runtime.workflows.catalog import AdkCatalogNodes, build_catalog_workflow


def _has_pinned_adk():
    try:
        return importlib.metadata.version("google-adk") == "2.7.1"
    except importlib.metadata.PackageNotFoundError:
        return False


def _nodes():
    def passthrough(node_input=None):
        return node_input

    return AdkCatalogNodes(
        validate_intent=passthrough,
        metadata=passthrough,
        vector=passthrough,
        access=passthrough,
        route_catalog=passthrough,
        existing_asset=passthrough,
        needs_input=passthrough,
        migrate=passthrough,
        fail_closed=passthrough,
    )


def test_factory_fails_closed_without_the_pinned_runtime(monkeypatch):
    monkeypatch.setattr(
        "agent_runtime.workflows.catalog.load_adk_patterns",
        lambda: (_ for _ in ()).throw(RuntimeError("wrong python")),
    )
    with pytest.raises(RuntimeError, match="wrong python"):
        build_catalog_workflow(_nodes())


@pytest.mark.skipif(
    sys.version_info[:2] != (3, 12)
    or not _has_pinned_adk(),
    reason="pinned ADK smoke test requires the isolated Python 3.12 runtime",
)
def test_factory_constructs_the_reviewed_adk_graph():
    workflow = build_catalog_workflow(_nodes())
    assert workflow.name == "catalog_first"
    assert workflow.max_concurrency == 4
    assert len(workflow.graph.edges) == 12
    assert {node.name for node in workflow.graph.nodes} == {
        "__START__",
        "validate_intent",
        "catalog_metadata",
        "catalog_vector",
        "catalog_access",
        "catalog_join",
        "route_catalog",
        "prepare_access_request",
        "source_intake",
        "source_portfolio",
        "catalog_fail_closed",
    }
