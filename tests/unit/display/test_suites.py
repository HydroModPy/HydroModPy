from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from hydromodpy.display.options import DisplayOptions, DisplaySectionOptions
from hydromodpy.display.suites import (
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)


def _build_result(
    *,
    flow_model,
    transport_model=None,
):
    geographic = SimpleNamespace(
        watershed_dem=Path("native_dem.tif"),
        watershed_shp=Path("watershed.shp"),
    )
    workspace = SimpleNamespace(simulations_folder=Path("simulations"))
    hydrography = SimpleNamespace(streams=Path("streams.shp"))

    class _Result:
        setup = SimpleNamespace(geographic=geographic, workspace=workspace)
        loaded_data = SimpleNamespace(hydrometry=None, hydrography=hydrography, recharge=None, piezometry=None)
        cfg = SimpleNamespace(workspace=SimpleNamespace(data_path=Path(".")))

        @staticmethod
        def get_model_for_solver(name: str):
            if name == "modflownwt":
                return flow_model
            if name == "modflow6":
                return None
            if name == "mt3dms":
                return transport_model
            if name == "modflow6gwt":
                return None
            return None

    return _Result()


def test_plot_flow_suite_uses_solver_base_raster(monkeypatch) -> None:
    flow_model = SimpleNamespace(
        model_name="flow_main",
        dem_watershed_path=Path("solver_grid_template.tif"),
    )
    result = _build_result(flow_model=flow_model)

    captured_dem: list[Path] = []
    monkeypatch.setattr(
        "hydromodpy.display.suites._load_flow_timeseries",
        lambda result: pd.DataFrame({"dummy": [0.0]}),
    )
    monkeypatch.setattr(
        "hydromodpy.display.suites._load_observed_streamflow",
        lambda result: pd.DataFrame({"Q": [0.0]}),
    )
    # Mock _extract_cross_section_data to capture the DEM path
    monkeypatch.setattr(
        "hydromodpy.display.suites._extract_cross_section_data",
        lambda dem_path, wt_path, x_index=None: (
            captured_dem.append(dem_path),
            (np.array([0.0]), np.array([0.0]), np.array([0.0])),
        )[1],
    )
    monkeypatch.setattr("hydromodpy.display.suites.plot_cross_section", lambda **kwargs: None)
    monkeypatch.setattr("hydromodpy.display.suites.plot_discharge", lambda **kwargs: None)
    monkeypatch.setattr("hydromodpy.display.suites.plot_piezometry", lambda **kwargs: None)

    options = DisplayOptions(
        enabled=True,
        show=True,
        save=False,
        flow=DisplaySectionOptions(
            enabled=True,
            flags={
                "cross_section": True,
                "streamflow": False,
                "piezometry": False,
            },
        ),
    )

    plot_flow_suite(result, options)

    assert captured_dem == [Path("solver_grid_template.tif")]


def test_plot_particles_suite_uses_solver_base_raster(monkeypatch) -> None:
    flow_model = SimpleNamespace(
        model_name="flow_main",
        dem_watershed_path=Path("solver_grid_template.tif"),
    )
    result = _build_result(flow_model=flow_model)

    captured: list[Path] = []

    # Mock geopandas.read_file (imported inside the function)
    _dummy_gdf = SimpleNamespace()
    monkeypatch.setattr(
        "geopandas.read_file",
        lambda path, **kw: _dummy_gdf,
    )
    monkeypatch.setattr(
        "hydromodpy.display.suites.plot_pathlines_map",
        lambda **kwargs: captured.append(kwargs["dem_path"]),
    )

    options = DisplayOptions(
        enabled=True,
        show=True,
        save=False,
        particles=DisplaySectionOptions(
            enabled=True,
            flags={"pathlines": True},
        ),
    )

    plot_particles_suite(result, options)

    assert captured == [Path("solver_grid_template.tif")]


def test_plot_transport_suite_passes_solver_base_raster(monkeypatch) -> None:
    flow_model = SimpleNamespace(
        model_name="flow_main",
        dem_watershed_path=Path("solver_grid_template.tif"),
    )
    transport_model = SimpleNamespace(name="transport")
    result = _build_result(flow_model=flow_model, transport_model=transport_model)

    captured: list[Path] = []
    monkeypatch.setattr(
        "hydromodpy.display.suites.plot_concentration_frames",
        lambda **kwargs: captured.append(kwargs["base_raster_path"]) or [],
    )

    options = DisplayOptions(
        enabled=True,
        show=True,
        save=False,
        transport=DisplaySectionOptions(
            enabled=True,
            flags={
                "concentration": True,
                "gif": False,
                "web_animation": False,
            },
        ),
    )

    plot_transport_suite(result, options)

    assert captured == [Path("solver_grid_template.tif")]
