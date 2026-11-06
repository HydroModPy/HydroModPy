"""The runtime loader: path policy, time window and optional geology domain."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.loading.loader import DataManagersRuntimeLoader
from hydromodpy.data.loading.plan import DataLoadPlan


def _plain_loader(tmp_path: Path) -> DataManagersRuntimeLoader:
    return DataManagersRuntimeLoader(
        config_path=tmp_path / "launcher.toml",
        data_plan=DataLoadPlan(),
    )


def test_resolve_manager_input_path_uses_section_override(tmp_path: Path) -> None:
    loader = _plain_loader(tmp_path)
    resolved = loader._resolve_manager_input_path(
        section={"hydro_path": "inputs/hydrography"},
        keys=("hydro_path",),
        default_root=tmp_path / "data",
    )
    assert resolved == (tmp_path / "inputs" / "hydrography").resolve()


def test_resolve_manager_input_path_falls_back_to_workspace_data(tmp_path: Path) -> None:
    loader = _plain_loader(tmp_path)
    default_root = tmp_path / "data"
    resolved = loader._resolve_manager_input_path(
        section={},
        keys=("hydro_path",),
        default_root=default_root,
    )
    assert resolved == default_root


SIM_WINDOW = ("2020-01-01", "2020-01-31")


def _ctx(**kwargs: Any) -> WorkflowContext:
    return cast(WorkflowContext, SimpleNamespace(**kwargs))


def _build_loader(tmp_path: Path, window: tuple[str, str] | None) -> DataManagersRuntimeLoader:
    loader = DataManagersRuntimeLoader(
        config_path=tmp_path / "launcher.toml",
        data_plan=DataLoadPlan(),
    )
    loader._resolve_simulation_time_window_dates = lambda result: window  # noqa: ARG005
    return loader


def test_section_without_dates_inherits_the_simulation_window(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path, SIM_WINDOW)
    section: dict[str, Any] = {"sources": []}

    loader._apply_simulation_window_dates(section, _ctx())

    assert section["date_start"] == "2020-01-01"
    assert section["date_end"] == "2020-01-31"


def test_declared_dates_win_over_the_simulation_window(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path, SIM_WINDOW)
    section: dict[str, Any] = {"date_start": "2010-01-01", "date_end": "2019-12-31"}

    loader._apply_simulation_window_dates(section, _ctx())

    assert section["date_start"] == "2010-01-01"
    assert section["date_end"] == "2019-12-31"


def test_no_simulation_window_leaves_the_section_untouched(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path, None)
    section: dict[str, Any] = {"sources": []}

    loader._apply_simulation_window_dates(section, _ctx())

    assert "date_start" not in section
    assert "date_end" not in section


def test_config_dates_win_for_a_simulation_or_overview_spec(tmp_path: Path) -> None:
    """water_quality reads its own window before falling back."""
    loader = _build_loader(tmp_path, SIM_WINDOW)
    spec = VARIABLE_SPECS["water_quality"]
    assert spec.period_source == "simulation_or_overview"
    cfg = SimpleNamespace(date_start="2001-01-01", date_end="2005-12-31")

    period = loader._resolve_period_for_spec(cfg, spec, _ctx(cfg=SimpleNamespace()))

    assert period == (datetime(2001, 1, 1), datetime(2005, 12, 31))


def test_simulation_window_is_the_fallback_for_a_simulation_or_overview_spec(
    tmp_path: Path,
) -> None:
    loader = _build_loader(tmp_path, SIM_WINDOW)
    cfg = SimpleNamespace(date_start=None, date_end=None)

    period = loader._resolve_period_for_spec(
        cfg,
        VARIABLE_SPECS["water_quality"],
        _ctx(cfg=SimpleNamespace()),
    )

    assert period == (datetime(2020, 1, 1), datetime(2020, 1, 31))


def test_overview_window_is_the_last_fallback(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path, None)
    cfg = SimpleNamespace(date_start=None, date_end=None)
    overview = SimpleNamespace(date_start="1999-01-01", date_end="1999-12-31")

    period = loader._resolve_period_for_spec(
        cfg,
        VARIABLE_SPECS["water_quality"],
        _ctx(cfg=SimpleNamespace(overview=overview)),
    )

    assert period == (datetime(1999, 1, 1), datetime(1999, 12, 31))


def test_config_spec_without_dates_has_no_period(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path, SIM_WINDOW)
    cfg = SimpleNamespace(date_start=None, date_end=None)

    period = loader._resolve_period_for_spec(
        cfg,
        VARIABLE_SPECS["recharge"],
        _ctx(cfg=SimpleNamespace()),
    )

    assert period is None


def _geology_loader() -> DataManagersRuntimeLoader:
    return DataManagersRuntimeLoader(
        config_path=__file__,
        data_plan=DataLoadPlan(explicit_types=("geology",)),
    )


def test_resolve_raster_support_falls_back_to_geographic_when_domain_is_none():
    """When setup.domain is None, geographic surface is used."""
    loader = _geology_loader()
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
    loader = _geology_loader()
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
    loader = _geology_loader()
    result = SimpleNamespace(
        setup=SimpleNamespace(domain=None, geographic=None),
    )
    resolved = loader._resolve_geology_raster_support(result)
    assert resolved is None


def test_geology_request_mask_covers_the_buffered_domain_box(tmp_path):
    """Geology is asked over the buffered-box DEM, not the smaller watershed."""
    box_dem = tmp_path / "watershed_box_buff_dem.tif"
    box_dem.write_bytes(b"")
    geographic = SimpleNamespace(
        watershed_box_buff_dem=str(box_dem),
        watershed_shp=str(tmp_path / "watershed.shp"),
    )
    assert DataManagersRuntimeLoader._geology_request_mask(geographic) == box_dem


def test_geology_request_mask_falls_back_to_the_watershed(tmp_path):
    """Without a buffered-box DEM on disk the watershed polygon is used."""
    geographic = SimpleNamespace(
        watershed_box_buff_dem=str(tmp_path / "absent.tif"),
        watershed_shp=str(tmp_path / "watershed.shp"),
    )
    assert DataManagersRuntimeLoader._geology_request_mask(geographic) == (
        tmp_path / "watershed.shp"
    )
