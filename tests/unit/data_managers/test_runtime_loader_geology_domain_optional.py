"""Tests for geology raster-support resolution when domain is optional."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.data.runtime_loader import DataManagersRuntimeLoader
from hydromodpy.data.plan import DataLoadPlan


def _build_loader() -> DataManagersRuntimeLoader:
    return DataManagersRuntimeLoader(
        config_path=__file__,
        data_plan=DataLoadPlan(explicit_types=("geology",)),
    )


def test_resolve_raster_support_falls_back_to_geographic_when_domain_is_none():
    """When setup.domain is None, geographic surface is used."""
    loader = _build_loader()
    support = object()
    result = SimpleNamespace(
        setup=SimpleNamespace(
            domain=None,
            geographic=SimpleNamespace(
                get_domain_surface_topo=lambda: SimpleNamespace(support=support),
            ),
        ),
    )
    resolved = loader._resolve_geology_raster_support(result)
    assert resolved is support


def test_resolve_raster_support_prefers_domain_when_available():
    """When setup.domain has surface_topo, use it over geographic."""
    loader = _build_loader()
    domain_support = object()
    geo_support = object()
    result = SimpleNamespace(
        setup=SimpleNamespace(
            domain=SimpleNamespace(
                surface_topo=SimpleNamespace(support=domain_support),
            ),
            geographic=SimpleNamespace(
                get_domain_surface_topo=lambda: SimpleNamespace(support=geo_support),
            ),
        ),
    )
    resolved = loader._resolve_geology_raster_support(result)
    assert resolved is domain_support


def test_resolve_raster_support_returns_none_when_no_domain_or_geographic():
    """When neither domain nor geographic is available, return None."""
    loader = _build_loader()
    result = SimpleNamespace(
        setup=SimpleNamespace(domain=None, geographic=None),
    )
    resolved = loader._resolve_geology_raster_support(result)
    assert resolved is None
