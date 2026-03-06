"""Tests for geology loading when launcher setup.domain is optional."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from hydromodpy.data_managers.plan import DataLoadPlan
from hydromodpy.data_managers.runtime_loader import DataManagersRuntimeLoader


def _build_loader() -> DataManagersRuntimeLoader:
    return DataManagersRuntimeLoader(
        config_path=__file__,
        data_plan=DataLoadPlan(explicit_types=("geology",)),
    )


def _install_fake_geology_field(monkeypatch, *, return_value):
    module_name = "hydromodpy.data_managers.geology.geology_field"
    fake_module = types.ModuleType(module_name)

    class FakeGeologyField:
        @staticmethod
        def from_watershed_config(geology_cfg, *, raster_support):
            return return_value(geology_cfg, raster_support)

    fake_module.GeologyField = FakeGeologyField
    monkeypatch.setitem(sys.modules, module_name, fake_module)


def test_loader_geology_falls_back_to_geographic_surface_when_domain_is_missing(monkeypatch) -> None:
    loader = _build_loader()
    captured: dict[str, object] = {}
    support = object()
    geology_cfg = object()

    _install_fake_geology_field(
        monkeypatch,
        return_value=lambda cfg, raster_support: (
            captured.update({"cfg": cfg, "support": raster_support}) or "geology_obj"
        ),
    )

    result = SimpleNamespace(
        cfg=SimpleNamespace(data=SimpleNamespace(geology=geology_cfg, inference_mode="strict")),
        setup=SimpleNamespace(
            domain=None,
            geographic=SimpleNamespace(
                get_domain_surface_topo=lambda: SimpleNamespace(support=support)
            ),
        ),
        loaded_data=SimpleNamespace(geology=None),
    )

    loader._load_geology_data(result)

    assert result.loaded_data.geology == "geology_obj"
    assert captured["cfg"] is geology_cfg
    assert captured["support"] is support


def test_loader_geology_prefers_domain_surface_when_available(monkeypatch) -> None:
    loader = _build_loader()
    captured: dict[str, object] = {}
    domain_support = object()
    geographic_support = object()

    _install_fake_geology_field(
        monkeypatch,
        return_value=lambda cfg, raster_support: (
            captured.update({"support": raster_support}) or "geology_obj"
        ),
    )

    result = SimpleNamespace(
        cfg=SimpleNamespace(data=SimpleNamespace(geology=object(), inference_mode="strict")),
        setup=SimpleNamespace(
            domain=SimpleNamespace(
                surface_topo=SimpleNamespace(support=domain_support),
            ),
            geographic=SimpleNamespace(
                get_domain_surface_topo=lambda: SimpleNamespace(support=geographic_support)
            ),
        ),
        loaded_data=SimpleNamespace(geology=None),
    )

    loader._load_geology_data(result)

    assert result.loaded_data.geology == "geology_obj"
    assert captured["support"] is domain_support


def test_loader_geology_raises_when_no_domain_or_geographic_support() -> None:
    loader = _build_loader()
    result = SimpleNamespace(
        cfg=SimpleNamespace(data=SimpleNamespace(geology=object(), inference_mode="strict")),
        setup=SimpleNamespace(domain=None, geographic=None),
        loaded_data=SimpleNamespace(geology=None),
    )

    with pytest.raises(ValueError, match="domain/geographic surface raster support"):
        loader._load_geology_data(result)
