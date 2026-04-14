from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg", force=True)

from hydromodpy.analysis.display.flow_payloads import (
    FlowCumulativeSeriesPayload,
    FlowSpatialFigurePayload,
)
from hydromodpy.analysis.display.display_config import DisplayOptions, DisplaySectionOptions
from hydromodpy.analysis.display.posthoc import GeographicArtifacts, RunArtifacts
from hydromodpy.analysis.display.posthoc_orchestration import plot_posthoc_flow_suite
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


def _build_spatial_payload(run_id: str = "run_a") -> FlowSpatialFigurePayload:
    hydro_mesh = HydroMesh(
        vertices=np.asarray(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        cell_blocks=(
            CellBlock(
                cell_type=CellType.TRIANGLE,
                connectivity=np.asarray([[0, 1, 2], [0, 2, 3]], dtype=int),
            ),
        ),
    )
    return FlowSpatialFigurePayload(
        run_id=run_id,
        hydro_mesh=hydro_mesh,
        top_elevation_m=np.asarray([10.0, 9.0], dtype=float),
        watertable_elevation_m=np.asarray([8.8, 8.3], dtype=float),
        watertable_depth_m=np.asarray([1.2, 0.7], dtype=float),
        seepage_areas_m_per_day=np.asarray([0.1, 0.0], dtype=float),
        outflow_drain_m_per_day=np.asarray([0.2, 0.4], dtype=float),
    )


def _build_cumulative_payload(run_id: str = "run_a") -> FlowCumulativeSeriesPayload:
    return FlowCumulativeSeriesPayload(
        run_id=run_id,
        time_days=np.asarray([0.0, 30.0, 60.0], dtype=float),
        recharge_cumulative_mm=np.asarray([5.0, 15.0, 25.0], dtype=float),
        discharge_components_cumulative_mm={
            "Drain discharge": np.asarray([1.0, 3.0, 5.0], dtype=float),
        },
        discharge_total_cumulative_mm=np.asarray([1.0, 3.0, 5.0], dtype=float),
    )


def test_plot_posthoc_flow_suite_reuses_native_mesh_figures_for_unstructured_outputs(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "results_simulations" / "run_a"
    postprocess_dir = run_dir / "_postprocess"
    native_dir = postprocess_dir / "_figures" / "native_mesh"
    native_dir.mkdir(parents=True, exist_ok=True)
    (native_dir / "flow_watertable_depth_t(0)_time(1).png").write_text("depth", encoding="utf-8")
    (native_dir / "flow_support_overview.png").write_text("overview", encoding="utf-8")

    np.save(
        postprocess_dir / "watertable_elevation",
        {0: np.asarray([9.0, 8.5], dtype=float)},
    )

    run = RunArtifacts.discover(run_dir)
    geo = GeographicArtifacts(geographic_dir=tmp_path / "results_stable" / "geographic")
    options = DisplayOptions(
        enabled=True,
        show=False,
        save=True,
        flow=DisplaySectionOptions(enabled=True),
    )

    plot_posthoc_flow_suite(run, geo, options)

    figure_dir = run_dir / "figures" / "run_a"
    assert (figure_dir / "watertable_depth.png").exists()
    assert (figure_dir / "flow_support_overview.png").exists()


def test_plot_posthoc_flow_suite_renders_solver_agnostic_common_figures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "results_simulations" / "run_a"
    postprocess_dir = run_dir / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    timeseries_dir = postprocess_dir / "_timeseries"
    timeseries_dir.mkdir(parents=True, exist_ok=True)
    (timeseries_dir / "_simulated_timeseries.csv").write_text(
        "date;recharge;outflow_drain;runoff\n"
        "2000-01-31;0.001;0.0005;0.0001\n"
        "2000-02-29;0.002;0.0007;0.0002\n",
        encoding="utf-8",
    )

    run = RunArtifacts.discover(run_dir)
    geo = GeographicArtifacts(geographic_dir=tmp_path / "results_stable" / "geographic")
    options = DisplayOptions(
        enabled=True,
        show=False,
        save=True,
        flow=DisplaySectionOptions(
            enabled=True,
            flags={
                "state_triptych": True,
                "recharge_discharge_cumulative": True,
                "watertable_map": True,
                "dem_map": False,
                "cross_section": False,
                "budget": False,
                "hydrography": False,
            },
        ),
    )

    monkeypatch.setattr(
        "hydromodpy.analysis.display.posthoc_orchestration.build_flow_spatial_payload_from_run",
        lambda run: _build_spatial_payload(run.run_id),
    )
    monkeypatch.setattr(
        "hydromodpy.analysis.display.posthoc_orchestration.build_flow_cumulative_payload",
        lambda simulated_timeseries, *, run_id: _build_cumulative_payload(run_id),
    )

    plot_posthoc_flow_suite(run, geo, options)

    figure_dir = run_dir / "figures" / "run_a"
    assert (figure_dir / "flow_state_triptych.png").exists()
    assert (figure_dir / "recharge_discharge_cumulative.png").exists()
    assert (figure_dir / "watertable_elevation.png").exists()
