from __future__ import annotations

from types import SimpleNamespace

import pytest

import hydromodpy.data.variables.dem.resolver as dem_resolver
import hydromodpy.workflow.pipelines.overview as overview_module
from hydromodpy.core.exceptions import ConfigMissingError


def test_inject_overview_dates_only_fills_missing_date_fields() -> None:
    recharge = SimpleNamespace(date_start=None, date_end=None)
    hydrography = SimpleNamespace(date_start="2020-03-01", date_end=None)
    state = SimpleNamespace(
        cfg=SimpleNamespace(
            overview=SimpleNamespace(date_start="2020-01-01", date_end="2020-12-31"),
            data=SimpleNamespace(
                types=("recharge", "hydrography", "static_layer", "missing"),
                recharge=recharge,
                hydrography=hydrography,
                static_layer=SimpleNamespace(path="static.gpkg"),
            ),
        )
    )

    overview_module.DataOverviewLauncher._inject_overview_dates(state)

    assert recharge.date_start == "2020-01-01"
    assert recharge.date_end == "2020-12-31"
    assert hydrography.date_start == "2020-03-01"
    assert hydrography.date_end == "2020-12-31"


def test_load_data_builds_proxy_and_attaches_hydrographic_network(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeLoader:
        def __init__(self, *, config_path, data_plan) -> None:
            captured["config_path"] = config_path
            captured["data_plan"] = data_plan

        def load_all(self, proxy) -> None:
            captured["proxy"] = proxy
            proxy.loaded_data.loaded_by_fake_loader = True

    def fake_attach(features, hydrography):
        captured["attached"] = (features, hydrography)
        return "features-with-network"

    monkeypatch.setattr(
        "hydromodpy.data.loader.DataManagersRuntimeLoader",
        FakeLoader,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.core.derived_features.attach_reference_hydrographic_network",
        fake_attach,
    )

    config_path = tmp_path / "overview.toml"
    launcher = object.__new__(overview_module.DataOverviewLauncher)
    launcher.config_path = config_path
    loaded_data = SimpleNamespace(hydrography="network")
    recharge = SimpleNamespace(date_start=None, date_end=None)
    state = SimpleNamespace(
        cfg=SimpleNamespace(
            data=SimpleNamespace(
                types=("recharge", "hydrography"),
                recharge=recharge,
                hydrography=SimpleNamespace(),
            ),
            workspace="workspace-config",
            overview=SimpleNamespace(date_start="2021-01-01", date_end="2021-01-31"),
        ),
        workspace="workspace-runtime",
        geographic="geographic-runtime",
        loaded_data=loaded_data,
        geographic_features="features",
    )

    launcher._load_data(state)

    proxy = captured["proxy"]
    assert captured["config_path"] == config_path
    assert captured["data_plan"].explicit_types == ("recharge", "hydrography")
    assert proxy.cfg.data is state.cfg.data
    assert proxy.cfg.workspace == "workspace-config"
    assert proxy.cfg.overview is state.cfg.overview
    assert proxy.setup.workspace == "workspace-runtime"
    assert proxy.setup.geographic == "geographic-runtime"
    assert proxy.loaded_data is loaded_data
    assert loaded_data.loaded_by_fake_loader is True
    assert recharge.date_start == "2021-01-01"
    assert captured["attached"] == ("features", "network")
    assert state.geographic_features == "features-with-network"


def test_bootstrap_dem_raises_when_no_path_or_data_source_can_resolve(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        dem_resolver,
        "resolve_dem_path_from_data_sources",
        lambda *args, **kwargs: None,
    )
    launcher = object.__new__(overview_module.DataOverviewLauncher)
    launcher.config_path = tmp_path / "overview.toml"
    state = SimpleNamespace(
        cfg=SimpleNamespace(
            geographic=SimpleNamespace(dem_init_path=None),
            data=SimpleNamespace(),
        ),
        workspace=SimpleNamespace(paths=SimpleNamespace(data_path=tmp_path / "data")),
    )

    with pytest.raises(ConfigMissingError, match="No dem_init_path"):
        launcher._bootstrap_dem(state)
