"""Trusted Google Cloud execution boundary for approved migration outputs.

Imports are deliberately lazy: Dataflow workers can load the fixed template
without pulling control-plane-only approval and interpreter dependencies into
the worker container.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "CloudBundle",
    "CloudBundleRejected",
    "CloudExecutionRejected",
    "CloudPortfolioResult",
    "CloudRuntimeConfig",
    "build_cloud_bundles",
    "execute_cloud_portfolio",
]


def __getattr__(name: str) -> Any:
    if name in {"CloudBundle", "CloudBundleRejected", "build_cloud_bundles"}:
        return getattr(import_module(".bundle", __name__), name)
    if name in {
        "CloudExecutionRejected",
        "CloudPortfolioResult",
        "CloudRuntimeConfig",
        "execute_cloud_portfolio",
    }:
        return getattr(import_module(".orchestrator", __name__), name)
    raise AttributeError(name)
