from __future__ import annotations

from types import SimpleNamespace

import pytest

import hydromodpy.data.variables.dem.resolver as dem_resolver
import hydromodpy.data.variables.hydrography.resolver as hydrography_resolver
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
        "hydromodpy.data.loading.loader.DataManagersRuntimeLoader",
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


def _burn_state(tmp_path, *, enabled=True, declared=None, sources=()):
    return SimpleNamespace(
        cfg=SimpleNamespace(
            geographic=SimpleNamespace(
                enforce_streams=SimpleNamespace(
                    enabled=enabled,
                    stream_geometry_path=declared,
                )
            ),
            data=SimpleNamespace(hydrography=SimpleNamespace(sources=list(sources))),
        ),
        workspace=SimpleNamespace(paths=SimpleNamespace(data_path=tmp_path / "data")),
    )


def _launcher(tmp_path):
    launcher = object.__new__(overview_module.DataOverviewLauncher)
    launcher.config_path = tmp_path / "overview.toml"
    return launcher


def test_bootstrap_stream_geometry_fills_the_burn_from_the_data_family(
    monkeypatch, tmp_path
) -> None:
    network = tmp_path / "network.gpkg"
    monkeypatch.setattr(
        hydrography_resolver,
        "resolve_stream_geometry_path_from_data_sources",
        lambda *args, **kwargs: network,
    )
    state = _burn_state(tmp_path, sources=[SimpleNamespace(source="custom")])

    _launcher(tmp_path)._bootstrap_stream_geometry(state)

    assert state.cfg.geographic.enforce_streams.stream_geometry_path == network


def test_bootstrap_stream_geometry_leaves_a_disabled_burn_alone(tmp_path) -> None:
    state = _burn_state(tmp_path, enabled=False, sources=[SimpleNamespace(source="custom")])

    _launcher(tmp_path)._bootstrap_stream_geometry(state)

    assert state.cfg.geographic.enforce_streams.stream_geometry_path is None


def test_bootstrap_stream_geometry_defers_when_no_hydrography_source_is_declared(
    tmp_path,
) -> None:
    """Same deferral as the run pipeline: the burn names the file it cannot read."""
    state = _burn_state(tmp_path, sources=[])

    _launcher(tmp_path)._bootstrap_stream_geometry(state)

    assert state.cfg.geographic.enforce_streams.stream_geometry_path is None


def test_bootstrap_stream_geometry_raises_when_the_data_family_holds_no_vector(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        hydrography_resolver,
        "resolve_stream_geometry_path_from_data_sources",
        lambda *args, **kwargs: None,
    )
    state = _burn_state(tmp_path, sources=[SimpleNamespace(source="custom")])

    with pytest.raises(ConfigMissingError, match="a raster one cannot be burned"):
        _launcher(tmp_path)._bootstrap_stream_geometry(state)


def test_bootstrap_dem_assigns_on_the_catchment_variant(monkeypatch, tmp_path) -> None:
    """``GeographicConfig.dem_init_path`` is a read-only property; the field is on the variant."""
    dem = tmp_path / "dem.tif"
    monkeypatch.setattr(
        dem_resolver,
        "resolve_dem_path_from_data_sources",
        lambda *args, **kwargs: dem,
    )
    catchment = SimpleNamespace(dem_init_path=None)
    state = SimpleNamespace(
        cfg=SimpleNamespace(
            geographic=SimpleNamespace(dem_init_path=None, catchment=catchment),
            data=SimpleNamespace(),
        ),
        workspace=SimpleNamespace(paths=SimpleNamespace(data_path=tmp_path / "data")),
    )

    _launcher(tmp_path)._bootstrap_dem(state)

    assert catchment.dem_init_path == dem
