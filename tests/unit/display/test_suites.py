from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from hydromodpy.analysis.display.options import DisplayOptions, DisplaySectionOptions
from hydromodpy.analysis.display.suites import (
    plot_boussinesq_flow_suite,
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)


def _build_result(
    *,
    flow_model,
    boussinesq_model=None,
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
            if name == "boussinesq":
                return boussinesq_model
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
        "hydromodpy.analysis.display.suites._load_flow_timeseries",
        lambda result: pd.DataFrame({"dummy": [0.0]}),
    )
    monkeypatch.setattr(
        "hydromodpy.analysis.display.suites._load_observed_streamflow",
        lambda result: pd.DataFrame({"Q": [0.0]}),
    )
    # Mock _extract_cross_section_data to capture the DEM path
    monkeypatch.setattr(
        "hydromodpy.analysis.display.suites._extract_cross_section_data",
        lambda dem_path, wt_path, x_index=None: (
            captured_dem.append(dem_path),
            (np.array([0.0]), np.array([0.0]), np.array([0.0])),
        )[1],
    )
    monkeypatch.setattr("hydromodpy.analysis.display.suites.plot_cross_section", lambda **kwargs: None)
    monkeypatch.setattr("hydromodpy.analysis.display.suites.plot_discharge", lambda **kwargs: None)
    monkeypatch.setattr("hydromodpy.analysis.display.suites.plot_piezometry", lambda **kwargs: None)

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
        "hydromodpy.analysis.display.suites.plot_pathlines_map",
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
        "hydromodpy.analysis.display.suites.plot_concentration_frames",
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


def test_plot_flow_suite_copies_native_mesh_figures_for_unstructured_solver(
    tmp_path,
    monkeypatch,
) -> None:
    native_dir = tmp_path / "flow_main" / "_postprocess" / "_figures" / "native_mesh"
    native_dir.mkdir(parents=True, exist_ok=True)
    (native_dir / "flow_watertable_depth_t(0)_time(1).png").write_text("depth", encoding="utf-8")
    (native_dir / "flow_support_overview.png").write_text("overview", encoding="utf-8")

    flow_model = SimpleNamespace(
        model_name="flow_main",
        full_path=tmp_path / "flow_main",
        solver_mesh=SimpleNamespace(is_structured=False),
    )
    result = _build_result(flow_model=flow_model)
    result.setup.workspace.simulations_folder = tmp_path

    monkeypatch.setattr(
        "hydromodpy.analysis.display.suites._load_flow_timeseries",
        lambda result: pd.DataFrame({"dummy": [0.0]}),
    )
    monkeypatch.setattr(
        "hydromodpy.analysis.display.suites._load_observed_streamflow",
        lambda result: None,
    )
    monkeypatch.setattr(
        "hydromodpy.analysis.display.suites._extract_cross_section_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cross section should be skipped")),
    )

    options = DisplayOptions(
        enabled=True,
        show=False,
        save=True,
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

    figure_dir = tmp_path / "flow_main" / "_postprocess" / "_figures"
    assert (figure_dir / "watertable_depth.png").exists()
    assert (figure_dir / "flow_support_overview.png").exists()


def test_plot_transport_suite_copies_native_mesh_figures_for_unstructured_solver(
    tmp_path,
    monkeypatch,
) -> None:
    native_dir = tmp_path / "flow_main" / "_postprocess" / "_figures" / "native_mesh"
    native_dir.mkdir(parents=True, exist_ok=True)
    (native_dir / "transport_concentration_seepage_t(0)_time(1).png").write_text(
        "transport",
        encoding="utf-8",
    )

    flow_model = SimpleNamespace(
        model_name="flow_main",
        full_path=tmp_path / "flow_main",
        solver_mesh=SimpleNamespace(is_structured=False),
    )
    transport_model = SimpleNamespace(name="transport")
    result = _build_result(flow_model=flow_model, transport_model=transport_model)
    result.setup.workspace.simulations_folder = tmp_path

    monkeypatch.setattr(
        "hydromodpy.analysis.display.suites.plot_concentration_frames",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("native mesh path should bypass raster concentration frames")),
    )

    options = DisplayOptions(
        enabled=True,
        show=False,
        save=True,
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

    figure_dir = tmp_path / "flow_main" / "_postprocess" / "_figures" / "transport"
    assert (figure_dir / "concentration_seepage.png").exists()


def test_plot_boussinesq_flow_suite_saves_figure(tmp_path) -> None:
    mesh = SimpleNamespace(
        node_x_m=np.array([0.0, 20.0, 0.0, 20.0], dtype=float),
        node_y_m=np.array([0.0, 0.0, 10.0, 10.0], dtype=float),
        cell_node_ids=((0, 1, 2), (1, 3, 2)),
        node_index_by_id={0: 0, 1: 1, 2: 2, 3: 3},
        cell_centroid_x_m=np.array([20.0 / 3.0, 40.0 / 3.0], dtype=float),
        z_top_m=np.array([12.0, 11.5], dtype=float),
        z_bottom_m=np.array([5.0, 5.0], dtype=float),
    )
    boussinesq_model = SimpleNamespace(
        model_name="bouss_main",
        mesh=mesh,
        state=SimpleNamespace(head_m=np.array([10.0, 9.5], dtype=float)),
    )
    result = _build_result(
        flow_model=None,
        boussinesq_model=boussinesq_model,
    )
    result.setup.workspace.simulations_folder = tmp_path

    options = DisplayOptions(
        enabled=True,
        show=False,
        save=True,
        flow=DisplaySectionOptions(enabled=True),
    )

    plot_boussinesq_flow_suite(result, options)

    assert (
        tmp_path
        / "bouss_main"
        / "_postprocess"
        / "_figures"
        / "boussinesq_state.png"
    ).exists()


def test_plot_boussinesq_flow_suite_emits_diagnostics_when_histories_exist(tmp_path) -> None:
    mesh = SimpleNamespace(
        cell_ids=np.array([10, 11], dtype=int),
        node_x_m=np.array([0.0, 20.0, 0.0, 20.0], dtype=float),
        node_y_m=np.array([0.0, 0.0, 10.0, 10.0], dtype=float),
        cell_node_ids=((0, 1, 2), (1, 3, 2)),
        node_index_by_id={0: 0, 1: 1, 2: 2, 3: 3},
        edge_node_a=np.array([0, 1, 2, 0, 1], dtype=int),
        edge_node_b=np.array([1, 3, 3, 2, 2], dtype=int),
        edge_cell_a=np.array([0, 1, 1, 0, 0], dtype=int),
        edge_cell_b=np.array([-1, -1, -1, -1, 1], dtype=int),
        cell_centroid_x_m=np.array([20.0 / 3.0, 40.0 / 3.0], dtype=float),
        cell_centroid_y_m=np.array([10.0 / 3.0, 20.0 / 3.0], dtype=float),
        cell_area_m2=np.array([100.0, 100.0], dtype=float),
        z_top_m=np.array([12.0, 11.5], dtype=float),
        z_bottom_m=np.array([5.0, 5.0], dtype=float),
        storage_coefficient=np.array([0.15, 0.15], dtype=float),
        boundary_edge_mask=np.array([True, True, True, True, False], dtype=bool),
    )
    state = SimpleNamespace(
        head_m=np.array([10.0, 9.5], dtype=float),
        head_history_m=np.array(
            [
                [9.5, 9.0],
                [9.8, 9.3],
                [10.0, 9.5],
            ],
            dtype=float,
        ),
        recharge_rate_history_m_s=np.array(
            [
                [0.0, 0.0],
                [1.0e-8, 1.0e-8],
                [1.0e-8, 1.0e-8],
            ],
            dtype=float,
        ),
        well_flux_history_m3_s=np.zeros((3, 2), dtype=float),
        saturation_excess_history_m_s=np.array(
            [
                [0.0, 0.0],
                [0.0, 0.0],
                [1.0e-9, 2.0e-9],
            ],
            dtype=float,
        ),
        internal_edge_flux_m3_s=np.array([0.0, 0.0, 0.0, 0.0, 1.0e-4], dtype=float),
        internal_edge_flux_history_m3_s=np.array(
            [
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 8.0e-5],
                [0.0, 0.0, 0.0, 0.0, 1.0e-4],
            ],
            dtype=float,
        ),
        imposed_head_edge_flux_m3_s=np.array([2.0e-5, -1.0e-5, 0.0, 0.0, 0.0], dtype=float),
        imposed_head_edge_flux_history_m3_s=np.array(
            [
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [1.0e-5, -5.0e-6, 0.0, 0.0, 0.0],
                [2.0e-5, -1.0e-5, 0.0, 0.0, 0.0],
            ],
            dtype=float,
        ),
        drainage_flux_m3_s=np.array([0.0, 1.0e-5], dtype=float),
        drainage_flux_history_m3_s=np.array(
            [
                [0.0, 0.0],
                [0.0, 5.0e-6],
                [0.0, 1.0e-5],
            ],
            dtype=float,
        ),
        saturation_excess_rate_m_s=np.array([1.0e-9, 2.0e-9], dtype=float),
        period_lengths_seconds=(86_400.0, 86_400.0),
    )
    boussinesq_model = SimpleNamespace(
        model_name="bouss_diag",
        mesh=mesh,
        state=state,
    )
    result = _build_result(flow_model=None, boussinesq_model=boussinesq_model)
    result.setup.workspace.simulations_folder = tmp_path

    options = DisplayOptions(
        enabled=True,
        show=False,
        save=True,
        flow=DisplaySectionOptions(enabled=True),
    )

    plot_boussinesq_flow_suite(result, options)

    figure_dir = tmp_path / "bouss_diag" / "_postprocess" / "_figures"
    assert (figure_dir / "boussinesq_state.png").exists()
    assert (figure_dir / "boussinesq_diagnostics.png").exists()
    assert (figure_dir / "boussinesq_edge_flux.png").exists()
    assert (figure_dir / "boussinesq_mass_balance.png").exists()
    assert (figure_dir / "boussinesq_probe_heads.png").exists()
