"""Tests merged by module."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import validation_cases.calibration.network_transient_b0.network_transient_html as report
from hydromodpy.core.scoring.metrics import log_floor, log_nse
from validation_cases.calibration.network_transient_b0.natural_observations import (
    discharge_log_nse_cost,
    natural_network_cost,
    score_natural_network_transient_candidate,
    write_natural_observation_package,
)
from validation_cases.calibration.network_transient_b0.network_cost import (
    active_network_mask,
    network_cost,
    network_distance_error,
    network_flux_error,
    network_length_error,
    positive_outflow,
)
from validation_cases.calibration.network_transient_b0.network_transient_html import (
    build_network_transient_html,
    inspect_network_transient_html_artifacts,
)
from validation_cases.calibration.network_transient_b0.network_transient_truth import (
    discharge_rmse_cost,
    mesh_cell_geometry,
    q_total_release_from_drain_by_cell,
    score_network_transient_candidate,
    score_network_transient_candidate_from_runs,
    write_network_transient_truth_package,
)

# From test_b0_html_helpers.py


class _Raster:
    def __init__(
        self,
        data: np.ndarray,
        *,
        transform: tuple[float, float, float, float, float, float] = (
            2.0,
            0.0,
            10.0,
            0.0,
            -3.0,
            50.0,
        ),
        nodata: float | None = None,
    ) -> None:
        self.data = data
        self.transform = transform
        self.nodata = nodata


def test_generate_figures_keeps_only_successful_writers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    figure_root = tmp_path / "figures"
    monkeypatch.setattr(report, "FIGURE_ROOT", figure_root)

    def write_png(*args: object) -> None:
        path = Path(args[-1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")

    def fail_writer(*args: object) -> None:
        del args
        raise RuntimeError("missing optional artifact")

    for name in (
        "_save_watershed_id_card",
        "_save_dem_context_map",
        "_save_steady_balance_didactic",
        "_save_recharge_chronicle_figure",
        "_save_q_timeseries_figure",
        "_save_objective_parameter_maps",
        "_save_objective_profile_cuts",
    ):
        monkeypatch.setattr(report, name, write_png)
    monkeypatch.setattr(report, "_save_outflow_map_grid", fail_writer)

    figures = report._generate_figures(
        truth_dir=tmp_path / "truth",
        k_rows=[{"mK": "0.65"}],
        score_rows=[{"candidate_id": "candidate"}],
        truth_q=[1.0, 2.0],
    )

    assert "outflow_drain_maps" not in figures
    assert set(figures) == {
        "watershed_id_card",
        "dem_context_map",
        "steady_balance_didactic",
        "recharge_chronicle",
        "q_total_release_timeseries",
        "objective_parameter_maps",
        "objective_profile_cuts",
    }
    assert all(path.is_file() for path in figures.values())


def test_prune_stale_figures_removes_only_unexpected_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    figure_root = tmp_path / "figures"
    figure_root.mkdir()
    keep = figure_root / "keep.png"
    stale = figure_root / "stale.png"
    other = figure_root / "notes.txt"
    keep.write_bytes(b"keep")
    stale.write_bytes(b"stale")
    other.write_text("not a figure", encoding="utf-8")
    monkeypatch.setattr(report, "FIGURE_ROOT", figure_root)

    report._prune_stale_figures({"keep": keep})

    assert keep.is_file()
    assert not stale.exists()
    assert other.is_file()


def test_run_dem_loader_skips_missing_rasters_and_squeezes_single_band() -> None:
    raster = _Raster(np.arange(4, dtype=float).reshape(1, 2, 2))
    calls: list[str] = []

    class Run:
        def geographic_raster(self, name: str) -> _Raster:
            calls.append(name)
            if name == "dem":
                return raster
            raise KeyError(name)

    dem, selected = report._load_run_dem(Run())

    assert calls == ["watershed_dem", "dem"]
    assert selected is raster
    assert dem is not None
    assert dem.shape == (2, 2)


def test_extent_from_affine_transform_uses_pixel_size_and_shape() -> None:
    raster = _Raster(np.zeros((2, 3)), transform=(5.0, 0.0, 100.0, 0.0, -10.0, 200.0))

    assert report._extent_from_transform(raster, (2, 3)) == [100.0, 115.0, 180.0, 200.0]
    assert report._extent_from_transform(SimpleNamespace(transform=None), (2, 3)) is None


def test_mark_watershed_outlet_adds_marker_when_metadata_is_valid() -> None:
    import matplotlib.pyplot as plt

    class Catalog:
        def read_geographic_metadata(self, sim_id: str) -> dict[str, str]:
            assert sim_id == "sim-1"
            return {"x_outlet": "10.5", "y_outlet": "20.25"}

    run = SimpleNamespace(_catalog=Catalog(), sim_id="sim-1")
    fig, ax = plt.subplots()
    try:
        report._mark_watershed_outlet(ax, run)
        assert len(ax.lines) == 1
        assert ax.lines[0].get_xdata()[0] == pytest.approx(10.5)
        assert ax.lines[0].get_ydata()[0] == pytest.approx(20.25)
    finally:
        plt.close(fig)


def test_topography_context_masks_nodata_and_converts_extent_to_relative_km() -> None:
    raster = _Raster(
        np.asarray([[1.0, -9999.0], [3.0, 4.0]]),
        transform=(100.0, 0.0, 1000.0, 0.0, -100.0, 2200.0),
        nodata=-9999.0,
    )

    class Run:
        def geographic_raster(self, name: str) -> _Raster:
            assert name == "watershed_dem"
            return raster

    context = report._topography_context(Run(), origin=(900.0, 2000.0))

    assert context is not None
    assert context["extent"] == pytest.approx([0.1, 0.3, 0.0, 0.2])
    assert np.ma.is_masked(context["data"][0, 1])


def test_recharge_values_are_read_from_source_transient_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[data.recharge]
sources = [{values = [1.0, 0.5, 2.0]}]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(report, "SOURCE_TRANSIENT_CONFIG", config)

    values = report._recharge_values_from_config()

    assert values.tolist() == [1.0, 0.5, 2.0]


def test_steady_balance_figure_requires_truth_normalization(tmp_path: Path) -> None:
    truth = tmp_path / "truth"
    truth.mkdir()
    (truth / "normalization.json").write_text('{"Q_ref_steady": 4.0}', encoding="utf-8")
    out = tmp_path / "steady.png"

    report._save_steady_balance_didactic(
        truth,
        [
            {"mK": "0.5", "q_total_m3_s": "3.0", "active_fraction": "0.25"},
            {"mK": "0.65", "q_total_m3_s": "4.0", "active_fraction": "0.5"},
        ],
        out,
    )

    assert out.is_file()


def test_objective_helpers_handle_non_positive_values_and_sparse_grids() -> None:
    import matplotlib.pyplot as plt

    plot_values, floor = report._log_objective_values(np.asarray([0.0, 2.0, np.nan, -1.0]))

    assert floor == pytest.approx(1.0)
    assert plot_values.tolist()[:2] == pytest.approx([1.0, 2.0])
    assert np.isnan(plot_values[2])
    assert report._nearest_value(np.asarray([0.1, 0.7, 1.2]), 0.8) == pytest.approx(0.7)
    assert report._axis_bounds(np.asarray([2.0, 2.0])) == pytest.approx((1.7, 2.3))

    fig, ax = plt.subplots()
    try:
        image = report._objective_grid_image(
            ax,
            np.asarray([0.0, 1.0, 0.0, 1.0]),
            np.asarray([0.0, 0.0, 1.0, 1.0]),
            np.asarray([1.0, 2.0, 3.0, 4.0]),
        )
        assert image is not None
    finally:
        plt.close(fig)


def test_truth_and_candidate_helpers_prefer_completed_non_truth_rows(tmp_path: Path) -> None:
    truth = tmp_path / "truth"
    truth.mkdir()
    (truth / "metadata.json").write_text(
        '{"mK_true": 0.65, "Sy_true": 0.05}',
        encoding="utf-8",
    )
    rows = [
        {"candidate_id": "truth_identity", "status": "completed", "J": "0.0"},
        {"candidate_id": "bad", "status": "failed", "J": "0.01"},
        {"candidate_id": "candidate_b", "status": "completed", "J": "0.3"},
        {"candidate_id": "candidate_a", "status": "completed", "J": "0.2"},
    ]

    assert report._truth_parameters(truth) == pytest.approx((0.65, 0.05))
    assert report._candidate_is_truth(rows[0])
    assert report._best_completed_candidate_id(rows) == "candidate_a"
    assert report._first_non_truth_candidate(rows) == rows[2]
    assert (
        report._network_map_source_label({"network_map_source": "transient_mean"})
        == "transient mean"
    )


def test_drain_series_prefers_transient_npz_and_reads_q_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report, "PATH_BASE", tmp_path)
    np.savez(tmp_path / "steady.npz", outflow_drain=np.asarray([1.0, 2.0]))
    np.savez(tmp_path / "transient.npz", outflow_drain=np.asarray([[3.0, 4.0]]))
    q_csv = tmp_path / "q.csv"
    q_csv.write_text("period,q_total_release\n0,1.5\n1,2.5\n", encoding="utf-8")

    drain = report._steady_drain_from_score_row(
        {
            "network_map_source": "transient_last",
            "transient_network_npz": "transient.npz",
            "steady_drain_npz": "steady.npz",
        }
    )
    series = report._q_total_release_series(
        score_rows=[{"candidate_id": "candidate", "transient_q_csv": "q.csv"}],
        truth_q=[9.0],
    )

    assert drain is not None
    assert drain.tolist() == [3.0, 4.0]
    assert series == {
        "synthetic reference": [9.0],
        "candidate": [1.5, 2.5],
    }


def test_mesh_context_from_truth_package_uses_bundle_and_outlet_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report, "PATH_BASE", tmp_path)
    config = tmp_path / "source.toml"
    config.write_text(
        "[geographic]\n\n[geographic.catchment]\nx_outlet = 10.0\ny_outlet = 20.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(report, "SOURCE_TRANSIENT_CONFIG", config)
    truth = tmp_path / "truth"
    mesh = tmp_path / "mesh"
    truth.mkdir()
    mesh.mkdir()
    (truth / "metadata.json").write_text('{"mesh_bundle": "mesh"}', encoding="utf-8")
    (mesh / "nodes.csv").write_text(
        "node_id,x,y\n0,10,20\n1,20,20\n2,20,30\n3,10,30\n",
        encoding="utf-8",
    )
    (mesh / "cells.csv").write_text(
        "cell_id,n0,n1,n2,n3,z_top_mean\n0,0,1,2,3,42.0\n",
        encoding="utf-8",
    )
    np.savez(truth / "cell_geometry.npz", centroids=np.asarray([[15.0, 25.0]]))

    context = report._mesh_context_from_truth_package(truth)

    assert context is not None
    assert context["origin"] == pytest.approx((10.0, 20.0))
    assert context["cell_topography"].tolist() == [42.0]
    np.testing.assert_allclose(
        context["polygons"][0],
        np.asarray([[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01]]),
    )


def test_relative_geometry_helpers_cover_bounds_colors_and_lines() -> None:
    shapely = pytest.importorskip("shapely.geometry")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    polygon = shapely.Polygon([(0, 0), (2, 0), (2, 2), (0, 0)])
    multiline = shapely.MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]])

    colors = report._drain_facecolors(
        np.asarray([0.0, 1.0, np.nan]),
        threshold=0.5,
        cmap=plt.get_cmap("viridis"),
        norm=Normalize(vmin=0.5, vmax=1.0),
    )
    line_coords = list(report._iter_geometry_line_coords(multiline))

    assert report._polygon_bounds([np.asarray([[0.0, 1.0], [2.0, 3.0]])]) == pytest.approx(
        (-0.06, 0.94, 2.06, 3.06)
    )
    assert colors.shape == (3, 4)
    assert colors[0, 3] == pytest.approx(0.16)
    assert colors[1, 3] == pytest.approx(0.88)
    assert len(list(report._iter_geometry_line_coords(polygon))) == 1
    assert len(line_coords) == 2


# From test_b0_html_reporting.py


def test_network_transient_html_artifact_contract_reports_required_inputs(
    tmp_path: Path,
) -> None:
    truth = tmp_path / "truth"
    truth.mkdir()
    (truth / "metadata.json").write_text("{}", encoding="utf-8")
    (truth / "normalization.json").write_text("{}", encoding="utf-8")
    (truth / "transient_q_total_release.csv").write_text(
        "period,q_total_release\n0,1.0\n",
        encoding="utf-8",
    )
    score = tmp_path / "scores.csv"
    score.write_text("candidate_id,status,J\nc01,completed,0.1\n", encoding="utf-8")

    report = inspect_network_transient_html_artifacts(
        real_root=tmp_path,
        source_transient_config=tmp_path / "missing.toml",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[truth],
        score_tables=[score],
    )

    assert report.ok
    assert report.truth_dir == truth.resolve()
    assert report.score_table == score.resolve()
    assert "truth.metadata_json" in report.available
    assert "score_table.completed_rows" in report.available
    assert "source_transient_config" in report.optional_missing


def test_network_transient_html_artifact_contract_warns_on_transient_network_map(
    tmp_path: Path,
) -> None:
    truth = tmp_path / "site_01_truth_package"
    truth.mkdir()
    (truth / "metadata.json").write_text(
        json.dumps({"site_id": "site_01", "mK_true": 0.65, "Sy_true": 0.05}),
        encoding="utf-8",
    )
    (truth / "normalization.json").write_text("{}", encoding="utf-8")
    (truth / "transient_q_total_release.csv").write_text(
        "period,q_total_release\n0,1.0\n",
        encoding="utf-8",
    )
    score = tmp_path / "site_01_scores.csv"
    score.write_text(
        "candidate_id,status,J,mK,Sy,network_map_source\n"
        "truth_mK_0p65_Sy_0p05,completed,0.0,0.65,0.05,transient_last\n",
        encoding="utf-8",
    )

    report = inspect_network_transient_html_artifacts(
        real_root=tmp_path,
        source_transient_config=tmp_path / "missing.toml",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[truth],
        score_tables=[score],
    )

    assert report.ok
    assert "score_table.non_steady_network_map_source=transient_last" in report.contract_warnings


def test_network_transient_html_artifact_contract_flags_missing_required(
    tmp_path: Path,
) -> None:
    report = inspect_network_transient_html_artifacts(
        real_root=tmp_path,
        source_transient_config=tmp_path / "missing.toml",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[tmp_path / "missing_truth"],
        score_tables=[tmp_path / "missing_scores.csv"],
    )

    assert not report.ok
    assert "truth_package" in report.required_missing
    assert "score_table" in report.required_missing


def test_network_transient_html_writes_reference_manifest(tmp_path: Path) -> None:
    real_root = tmp_path / "real_runs"
    truth = real_root / "site_01_truth_package_mK_0p65"
    truth.mkdir(parents=True)
    (truth / "metadata.json").write_text(
        json.dumps(
            {
                "site_id": "site_01",
                "mK_true": 0.65,
                "Sy_true": 0.05,
                "n_cells": 3,
                "n_timesteps": 1,
            }
        ),
        encoding="utf-8",
    )
    (truth / "normalization.json").write_text(
        json.dumps({"Qbar_ref": 1.0, "w_reseau": 0.5, "w_debit": 0.5}),
        encoding="utf-8",
    )
    (truth / "transient_q_total_release.csv").write_text(
        "period,q_total_release\n0,1.0\n",
        encoding="utf-8",
    )
    score = real_root / "site_01_parameter_grid_light_scores_mK_0p65.csv"
    score.write_text(
        "candidate_id,status,J,mK,Sy,steady_drain_npz\n"
        "truth_mK_0p65_Sy_0p05,completed,0.0,0.65,0.05,steady.npz\n",
        encoding="utf-8",
    )

    out = build_network_transient_html(
        real_root=real_root,
        web_root=tmp_path / "web",
        source_transient_config=tmp_path / "missing.toml",
        reference_run_root=tmp_path / "missing_reference",
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[truth],
        score_tables=[score],
        page_title="Manifest smoke",
    )

    manifest = json.loads((real_root / "b0_reference_manifest.json").read_text("utf-8"))
    assert out == tmp_path / "web" / "index.html"
    assert manifest["contract_version"] == "b0_network_steady_discharge_transient.v1"
    assert manifest["paths"]["score_table"] == str(score.resolve())
    assert manifest["grid"]["completed"] == 1
    assert manifest["best_global"]["candidate_id"] == "truth_mK_0p65_Sy_0p05"

    # Page structure. These assertions used to live in a smoke test gated on
    # examples/**/outputs/, which .gitignore excludes, so they never ran in CI.
    text = out.read_text(encoding="utf-8")
    for marker in (
        "Calibration problem",
        "Spatial and temporal setup",
        "Objective function over the parameter space",
        "Drainage maps against the target",
        "Flux series",
    ):
        assert marker in text, f"missing section: {marker}"

    # The four remaining figures of the full report need a reference run and a
    # steady summary; this fixture deliberately points both at missing paths.
    for figure_name in (
        "objective_parameter_maps.png",
        "q_total_release_timeseries.png",
        "watershed_id_card.png",
    ):
        assert (tmp_path / "web" / "figures" / figure_name).is_file(), figure_name

    artifact_report = json.loads(
        (tmp_path / "web" / "network_transient_html_artifacts.json").read_text(encoding="utf-8")
    )
    assert artifact_report["ok"] is True


def test_network_transient_html_uses_truth_mesh_when_reference_run_is_empty(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real_runs"
    truth = real_root / "natural_observation_package"
    truth.mkdir(parents=True)
    mesh_bundle = real_root / "mesh_bundle"
    _write_line_mesh_bundle(mesh_bundle, n_cells=4)

    (truth / "metadata.json").write_text(
        json.dumps(
            {
                "site_id": "natural_site",
                "mesh_bundle": str(mesh_bundle.resolve()),
                "n_cells": 4,
                "n_timesteps": 2,
            }
        ),
        encoding="utf-8",
    )
    (truth / "normalization.json").write_text(
        json.dumps(
            {
                "contract_version": "natural_network_steady_discharge_transient.v1",
                "tau_network": 0.0,
                "Qbar_ref": 1.0,
                "w_reseau": 0.3,
                "w_debit": 0.7,
            }
        ),
        encoding="utf-8",
    )
    (truth / "transient_q_total_release.csv").write_text(
        "period,q_total_release\n0,1.0\n1,1.1\n",
        encoding="utf-8",
    )
    np.savez_compressed(
        truth / "steady_network_drain_by_cell.npz",
        outflow_drain=np.array([0.0, 1.0, 1.0, 0.0]),
    )
    np.savez_compressed(
        truth / "cell_geometry.npz",
        centroids=np.column_stack([np.arange(4, dtype=float), np.zeros(4, dtype=float)]),
        cell_area=np.ones(4, dtype=float),
    )

    candidates = real_root / "candidates"
    candidates.mkdir()
    np.savez_compressed(
        candidates / "shifted.npz",
        outflow_drain=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    score = real_root / "natural_site_scores.csv"
    score.write_text(
        "candidate_id,status,J,mK,Sy,network_map_source,steady_drain_npz,"
        "C_reseau_phys,C_debit_phys\n"
        "truth_identity,completed,0.0,0.65,0.05,steady,candidates/shifted.npz,0.0,0.0\n"
        "shifted,completed,0.2,0.95,0.05,steady,candidates/shifted.npz,0.2,0.0\n",
        encoding="utf-8",
    )
    empty_reference = real_root / "candidate_mK_0p65_Sy_0p05_steady_mf6"
    empty_reference.mkdir()

    build_network_transient_html(
        real_root=real_root,
        web_root=tmp_path / "web",
        source_transient_config=tmp_path / "missing.toml",
        path_base=real_root,
        reference_run_root=empty_reference,
        steady_summary_csv=tmp_path / "missing_steady.csv",
        truth_packages=[truth],
        score_tables=[score],
        page_title="Natural mesh fallback smoke",
    )

    assert (tmp_path / "web" / "figures" / "dem_context_map.png").is_file()
    assert (tmp_path / "web" / "figures" / "outflow_drain_maps.png").is_file()
    manifest = json.loads((real_root / "b0_reference_manifest.json").read_text("utf-8"))
    assert manifest["contract_version"] == "natural_network_steady_discharge_transient.v1"
    assert manifest["contract"]["objective"] == "0.3*C_reseau_naturel + 0.7*C_debit_obs"


def test_workflow_step_delegates_network_transient_html_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from validation_cases.calibration.network_transient_b0.network_transient_html import (
        step_render_network_transient_calibration_html,
    )

    captured: dict[str, object] = {}
    expected = tmp_path / "web" / "index.html"

    def fake_builder(**kwargs: object) -> Path:
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        "validation_cases.calibration.network_transient_b0.network_transient_html.build_network_transient_html",
        fake_builder,
    )

    out = step_render_network_transient_calibration_html(
        real_root=tmp_path / "real_runs",
        web_root=tmp_path / "web",
        page_title="Synthetic calibration",
    )

    assert out == expected
    assert captured["real_root"] == tmp_path / "real_runs"
    assert captured["web_root"] == tmp_path / "web"
    assert captured["page_title"] == "Synthetic calibration"


def _write_line_mesh_bundle(bundle_dir: Path, *, n_cells: int) -> None:
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "nodes.csv").write_text(
        "node_id,x,y\n"
        + "".join(
            f"{idx},{float(idx) - 0.5},-0.5\n{idx + n_cells + 1},{float(idx) - 0.5},0.5\n"
            for idx in range(n_cells + 1)
        ),
        encoding="utf-8",
    )
    (bundle_dir / "cells.csv").write_text(
        "cell_id,n0,n1,n2,n3,area_m2,z_top_mean\n"
        + "".join(
            f"{cell_id},{cell_id},{cell_id + 1},{cell_id + n_cells + 2},"
            f"{cell_id + n_cells + 1},1.0,{10.0 - cell_id}\n"
            for cell_id in range(n_cells)
        ),
        encoding="utf-8",
    )


# From test_b0_natural_observations.py


def _line_geometry(n_cells: int = 5) -> tuple[np.ndarray, np.ndarray]:
    centroids = np.column_stack([np.arange(n_cells, dtype=float), np.zeros(n_cells, dtype=float)])
    area = np.ones(n_cells, dtype=float)
    return centroids, area


def _line_distance_to_observed_network(n_cells: int = 5, *, center: float = 1.5) -> np.ndarray:
    return np.abs(np.arange(n_cells, dtype=float) - float(center))


def test_natural_network_cost_is_zero_for_same_support() -> None:
    centroids, area = _line_geometry()
    observed = np.array([False, True, True, False, False])
    candidate = np.array([0.0, 2.0, 1.0, 0.0, 0.0])
    distance = _line_distance_to_observed_network()

    score = natural_network_cost(
        candidate,
        observed,
        distance,
        centroids,
        area,
        d_tol=1.0,
    )

    assert score.total == pytest.approx(0.0)
    assert score.components["E_dist"] == pytest.approx(0.0)
    assert score.components["distance_ratio"] == pytest.approx(1.0)
    assert "C_len" not in score.components


def test_natural_network_cost_penalizes_shifted_support() -> None:
    centroids, area = _line_geometry()
    observed = np.array([False, True, True, False, False])
    candidate = np.array([0.0, 0.0, 0.0, 2.0, 1.0])
    distance = _line_distance_to_observed_network()

    score = natural_network_cost(
        candidate,
        observed,
        distance,
        centroids,
        area,
        d_tol=1.0,
    )

    assert score.total > 0.0
    assert score.components["E_dist"] > 0.0
    assert score.components["E_dist_ratio_abs_minus_one"] == pytest.approx(3.0)


def test_write_natural_package_and_score_identity(tmp_path: Path) -> None:
    centroids, area = _line_geometry()
    observed_network = np.array([False, True, True, False, False])
    observed_distance = _line_distance_to_observed_network()
    observed_q = np.array([1.0, 1.2, 0.8, 1.1])

    summary = write_natural_observation_package(
        tmp_path,
        observed_q_total_release=observed_q,
        observed_network_mask=observed_network,
        observed_network_distance_by_cell=observed_distance,
        centroids=centroids,
        cell_area=area,
        metadata={"site_id": "unit"},
        d_tol=1.0,
    )

    score = score_natural_network_transient_candidate(
        tmp_path,
        candidate_steady_drain_by_cell=observed_network.astype(float),
        candidate_q_total_release=observed_q,
    )
    metadata = json.loads((tmp_path / "metadata.json").read_text("utf-8"))
    normalization = json.loads((tmp_path / "normalization.json").read_text("utf-8"))

    assert summary.n_observed_network_active == 2
    assert score.total == pytest.approx(0.0)
    assert score.components["C_reseau_naturel"] == pytest.approx(0.0)
    assert score.components["C_debit_obs"] == pytest.approx(0.0)
    assert score.components["discharge.NSElog"] == pytest.approx(1.0)
    assert metadata["package_type"] == "natural_observation_package"
    assert metadata["discharge_observable"] == "observed_streamflow_nse_log"
    assert normalization["discharge_metric"] == "nse_log"
    assert not (tmp_path / "steady_network_drain_by_cell.npz").exists()
    assert (tmp_path / "steady_network_active_mask.npz").is_file()
    assert (tmp_path / "transient_q_total_release.csv").is_file()
    assert (tmp_path / "observed_network_distance_by_cell.npz").is_file()


def test_score_natural_candidate_combines_network_and_discharge(tmp_path: Path) -> None:
    centroids, area = _line_geometry()
    observed_network = np.array([False, True, True, False, False])
    observed_distance = _line_distance_to_observed_network()
    observed_q = np.array([0.8, 1.0, 1.4, 1.1])
    write_natural_observation_package(
        tmp_path,
        observed_q_total_release=observed_q,
        observed_network_mask=observed_network,
        observed_network_distance_by_cell=observed_distance,
        centroids=centroids,
        cell_area=area,
        d_tol=1.0,
    )

    score = score_natural_network_transient_candidate(
        tmp_path,
        candidate_steady_drain_by_cell=np.array([0.0, 0.0, 0.0, 1.0, 1.0]),
        candidate_q_total_release=np.array([2.0, 2.0, 2.0, 2.0]),
    )

    assert score.total > 0.0
    assert score.components["C_reseau_naturel"] > 0.0
    assert score.components["C_debit_obs"] > 0.0


def test_discharge_log_nse_cost_is_zero_for_perfect_series() -> None:
    q_obs = np.array([0.8, 1.0, 1.3, 1.1])

    cost, components = discharge_log_nse_cost(q_obs, q_obs)

    assert cost == pytest.approx(0.0)
    assert components["NSElog"] == pytest.approx(1.0)


def test_discharge_log_nse_cost_penalizes_low_flow_ratio_errors() -> None:
    q_obs = np.array([0.2, 0.4, 1.0, 2.0])
    q_sim = np.array([0.4, 0.8, 1.0, 2.0])

    cost, components = discharge_log_nse_cost(q_sim, q_obs)

    assert cost > 0.0
    assert components["NSElog"] < 1.0


def test_the_natural_prototype_reports_the_floor_of_the_scored_pairs() -> None:
    sim = np.array([1.0, 2.0, 3.0, np.nan, 5.0])
    obs = np.array([1.2, 1.9, 3.3, 900.0, 4.6])

    cost, diagnostics = discharge_log_nse_cost(sim, obs)

    scored = obs[np.isfinite(sim)]
    assert diagnostics["nse_log_epsilon"] == log_floor(scored)
    assert cost == pytest.approx(1.0 - log_nse(sim, obs, eps=log_floor(scored)))


# From test_b0_network_cost.py
# Unit tests for physical network calibration metrics.


def _grid_5x5() -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.meshgrid(np.arange(5, dtype=float), np.arange(5, dtype=float), indexing="ij")
    centroids = np.column_stack([xx.reshape(-1), yy.reshape(-1)])
    cell_area = np.ones(25, dtype=float)
    return centroids, cell_area


def _reference_network() -> np.ndarray:
    ref = np.zeros((5, 5), dtype=float)
    ref[:, 2] = 1.0
    ref[2, 3] = 0.2
    return ref.reshape(-1)


def test_positive_outflow_removes_negative_nan_and_nodata_values() -> None:
    out = positive_outflow([1.0, -2.0, np.nan, -9999.0, 0.5])
    np.testing.assert_allclose(out, [1.0, 0.0, 0.0, 0.0, 0.5])
    assert active_network_mask(out).tolist() == [True, False, False, False, True]


def test_identical_network_has_zero_cost() -> None:
    centroids, cell_area = _grid_5x5()
    ref = _reference_network()

    out = network_cost(ref, ref, centroids, cell_area, d_tol=1.0)

    assert out.total == pytest.approx(0.0)
    assert out.components["E_flux"] == pytest.approx(0.0)
    assert out.components["E_dist"] == pytest.approx(0.0)
    assert out.components["E_len"] == pytest.approx(0.0)


def test_network_shifted_by_one_cell_has_distance_error_near_one() -> None:
    centroids, _ = _grid_5x5()
    ref_grid = np.zeros((5, 5), dtype=float)
    ref_grid[:, 2] = 1.0
    sim = np.roll(ref_grid, shift=1, axis=1).reshape(-1)

    err = network_distance_error(sim, ref_grid.reshape(-1), centroids, d_tol=1.0)

    assert err == pytest.approx(1.0)


def test_empty_simulated_network_gets_finite_distance_penalty() -> None:
    centroids, cell_area = _grid_5x5()
    ref = _reference_network()
    sim = np.zeros_like(ref)

    err = network_distance_error(sim, ref, centroids, d_tol=1.0, empty_distance_penalty=7.0)
    out = network_cost(
        sim,
        ref,
        centroids,
        cell_area,
        d_tol=1.0,
        empty_distance_penalty=7.0,
    )

    assert err == pytest.approx(7.0)
    assert out.components["E_dist"] == pytest.approx(7.0)
    assert np.isfinite(out.total)
    assert out.total > 0.0


def test_missing_main_axis_penalizes_more_than_missing_side_branch() -> None:
    ref = _reference_network()
    missing_main = ref.reshape(5, 5).copy()
    missing_main[:, 2] = 0.0
    missing_branch = ref.reshape(5, 5).copy()
    missing_branch[2, 3] = 0.0

    main_error = network_flux_error(missing_main.reshape(-1), ref)
    branch_error = network_flux_error(missing_branch.reshape(-1), ref)

    assert main_error > branch_error
    assert main_error == pytest.approx(5.0 / 5.2)
    assert branch_error == pytest.approx(0.2 / 5.2)


def test_double_width_network_has_unit_length_error() -> None:
    _, cell_area = _grid_5x5()
    ref = np.zeros((5, 5), dtype=bool)
    ref[:, 2] = True
    sim = ref.copy()
    sim[:, 1] = True

    err = network_length_error(sim.reshape(-1), ref.reshape(-1), cell_area, d_tol=1.0)

    assert err == pytest.approx(1.0)


def test_empty_reference_network_is_invalid() -> None:
    centroids, cell_area = _grid_5x5()
    ref = np.zeros(25, dtype=float)
    sim = np.zeros(25, dtype=float)

    with pytest.raises(ValueError, match="q_ref_steady"):
        network_flux_error(sim, ref)
    with pytest.raises(ValueError, match="q_ref_steady"):
        network_cost(sim, ref, centroids, cell_area, d_tol=1.0)


def test_component_weights_are_normalized() -> None:
    centroids, cell_area = _grid_5x5()
    ref = _reference_network()
    sim = np.zeros_like(ref)

    out = network_cost(
        sim,
        ref,
        centroids,
        cell_area,
        d_tol=1.0,
        weight_flux=4.0,
        weight_dist=4.0,
        weight_len=2.0,
        empty_distance_penalty=1.0,
    )

    assert out.components["weight_flux"] == pytest.approx(0.4)
    assert out.components["weight_dist"] == pytest.approx(0.4)
    assert out.components["weight_len"] == pytest.approx(0.2)


def test_binary_reference_is_refused_where_a_flux_is_required() -> None:
    centroids, cell_area = _grid_5x5()
    mask_ref = np.zeros((5, 5), dtype=float)
    mask_ref[:, 2] = 1.0
    ref = mask_ref.reshape(-1)
    sim = _reference_network()

    with pytest.raises(ValueError, match="binary 0/1 mask"):
        network_flux_error(sim, ref)
    with pytest.raises(ValueError, match="per-cell drainage outflow"):
        network_cost(sim, ref, centroids, cell_area, d_tol=1.0)


def test_binary_reference_message_reports_what_it_got_and_what_it_needed() -> None:
    ref = np.array([0.0, 1.0, 0.0, 1.0])
    sim = np.array([0.0, 2.5, 0.0, 1.5])

    with pytest.raises(ValueError) as excinfo:
        network_flux_error(sim, ref)

    message = str(excinfo.value)
    assert "4 cells" in message
    assert "2 active" in message
    assert "per-cell drainage outflow" in message


def test_natural_observation_package_writes_no_flux_named_mask(tmp_path) -> None:
    from validation_cases.calibration.network_transient_b0.natural_observations import (
        write_natural_observation_package,
    )

    centroids = np.column_stack([np.arange(5, dtype=float), np.zeros(5)])
    write_natural_observation_package(
        tmp_path,
        observed_q_total_release=np.array([1.0, 1.2, 0.9]),
        observed_network_mask=np.array([False, True, True, False, False]),
        observed_network_distance_by_cell=np.array([1.0, 0.0, 0.0, 1.0, 2.0]),
        centroids=centroids,
        cell_area=np.ones(5),
        d_tol=1.0,
    )

    assert not (tmp_path / "steady_network_drain_by_cell.npz").exists()
    assert (tmp_path / "steady_network_active_mask.npz").is_file()
    assert (tmp_path / "observed_network_active_mask.npz").is_file()


def test_network_cost_module_exposes_network_cost() -> None:
    # Not a 0/1 vector: network_cost refuses a binary mask where a
    # per-cell outflow is required, which is the trap this guards.
    sim = np.array([0.0, 1.0, 0.0, 0.5])
    ref = np.array([0.0, 1.0, 0.0, 0.5])
    centroids = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    cell_area = np.ones(4)
    cost = network_cost(
        sim,
        ref,
        centroids,
        cell_area,
        d_tol=1.0,
    )
    assert cost.total == pytest.approx(0.0)


# From test_b0_network_transient_truth.py


def test_mesh_cell_geometry_handles_triangle_and_quad() -> None:
    vertices = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
            [2.0, 0.0],
        ],
        dtype=float,
    )
    faces = np.array(
        [
            [0, 1, 2, 3],
            [1, 4, 2, -1],
        ],
        dtype=int,
    )

    centroids, area = mesh_cell_geometry(vertices, faces)

    np.testing.assert_allclose(centroids[0], [0.5, 0.5])
    np.testing.assert_allclose(centroids[1], [4.0 / 3.0, 1.0 / 3.0])
    np.testing.assert_allclose(area, [1.0, 0.5])


def test_q_total_release_from_drain_by_cell_sums_positive_rows() -> None:
    drain = np.array(
        [
            [1.0, -2.0, 0.5],
            [0.0, 3.0, np.nan],
        ]
    )

    out = q_total_release_from_drain_by_cell(drain)

    np.testing.assert_allclose(out, [1.5, 3.0])


def test_discharge_rmse_cost_uses_fraction_of_mean_reference() -> None:
    cost, components = discharge_rmse_cost(
        [1.1, 1.9, 3.0],
        [1.0, 2.0, 3.0],
        alpha_q=0.10,
    )

    rmse = np.sqrt((0.1**2 + 0.1**2) / 3.0)
    assert components["RMSE_Q"] == pytest.approx(rmse)
    assert components["Qbar_ref"] == pytest.approx(2.0)
    assert cost == pytest.approx(rmse / 0.2)


def test_write_truth_package_and_score_identity(tmp_path) -> None:
    steady = np.array([1.0, 2.0, 0.0, 1.0], dtype=float)
    q_ref = np.array([0.5, 1.0, 2.0, 3.0], dtype=float)
    centroids = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
        ],
        dtype=float,
    )
    area = np.ones(4, dtype=float)
    time_index = pd.date_range("2020-01-01", periods=4, freq="MS")

    summary = write_network_transient_truth_package(
        tmp_path,
        steady_drain_by_cell=steady,
        transient_q_total_release=q_ref,
        centroids=centroids,
        cell_area=area,
        time_index=time_index,
        metadata={"site_id": "synthetic"},
        d_tol=1.0,
        warmup_periods=1,
        scored_periods=3,
    )
    score = score_network_transient_candidate(
        tmp_path,
        candidate_steady_drain_by_cell=steady,
        candidate_q_total_release=q_ref,
    )

    assert summary.q_ref_steady == pytest.approx(4.0)
    assert summary.qbar_ref == pytest.approx(2.0)
    assert summary.n_ref_active == 3
    assert score.total == pytest.approx(0.0)
    assert score.components["C_reseau_phys"] == pytest.approx(0.0)
    assert score.components["C_debit_phys"] == pytest.approx(0.0)

    normalization = json.loads((tmp_path / "normalization.json").read_text(encoding="utf-8"))
    assert normalization["score_start_index"] == 1
    assert normalization["score_stop_index"] == 4
    assert (tmp_path / "steady_network_drain_by_cell.npz").is_file()
    assert (tmp_path / "transient_q_total_release.csv").is_file()


def test_score_candidate_combines_network_and_discharge_costs(tmp_path) -> None:
    steady = np.array([1.0, 0.5, 0.0, 0.0], dtype=float)
    q_ref = np.array([1.0, 1.0, 1.0], dtype=float)
    centroids = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
        ],
        dtype=float,
    )
    area = np.ones(4, dtype=float)

    write_network_transient_truth_package(
        tmp_path,
        steady_drain_by_cell=steady,
        transient_q_total_release=q_ref,
        centroids=centroids,
        cell_area=area,
        d_tol=1.0,
        eta_flux=1.0,
        eta_dist=1.0,
        eta_len=1.0,
        alpha_q=0.5,
    )

    score = score_network_transient_candidate(
        tmp_path,
        candidate_steady_drain_by_cell=np.zeros_like(steady),
        candidate_q_total_release=np.array([1.5, 1.5, 1.5]),
    )

    assert score.components["C_reseau_phys"] > 0.0
    assert score.components["C_debit_phys"] == pytest.approx(1.0)
    assert score.total == pytest.approx(
        0.5 * score.components["C_reseau_phys"] + 0.5 * score.components["C_debit_phys"]
    )


def test_score_candidate_from_runs_uses_outflow_drain_fields(tmp_path) -> None:
    steady = np.array([1.5, 0.0, 0.5], dtype=float)
    q_ref = np.array([2.0, 2.0], dtype=float)
    centroids = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]], dtype=float)
    area = np.ones(3, dtype=float)
    write_network_transient_truth_package(
        tmp_path,
        steady_drain_by_cell=steady,
        transient_q_total_release=q_ref,
        centroids=centroids,
        cell_area=area,
        d_tol=1.0,
    )

    class _Stack:
        def __init__(self, data):
            self.data = np.asarray(data, dtype=float)

    class _Run:
        def __init__(self, steady_field=None, stack=None):
            self._steady_field = steady_field
            self._stack = stack

        def field(self, variable, time=-1):
            del time
            assert variable == "outflow_drain"
            return self._steady_field

        def fields(self, variable):
            assert variable == "outflow_drain"
            return _Stack(self._stack)

    score = score_network_transient_candidate_from_runs(
        tmp_path,
        steady_run=_Run(steady_field=steady),
        transient_run=_Run(stack=np.array([[1.5, 0.0, 0.5], [1.5, 0.0, 0.5]])),
    )

    assert score.total == pytest.approx(0.0)


# From test_b0_score_candidate_table.py


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "validation_cases"
    / "calibration"
    / "network_transient_b0"
    / "score_candidate_table.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("b0_score_candidate_table", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_load_candidate_specs_defaults_transient_catalog(tmp_path) -> None:
    module = _load_script_module()
    table = tmp_path / "candidates.csv"
    table.write_text(
        "\n".join(
            [
                "candidate_id,mK,Sy,steady_catalog,steady_ref,transient_ref",
                "c1,1.0,0.05,/tmp/steady.duckdb,steady_run,transient_run",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    specs = module.load_candidate_specs(table)

    assert specs == [
        {
            "candidate_id": "c1",
            "mK": "1.0",
            "Sy": "0.05",
            "steady_catalog": "/tmp/steady.duckdb",
            "steady_ref": "steady_run",
            "transient_ref": "transient_run",
            "transient_catalog": "/tmp/steady.duckdb",
        }
    ]


def test_load_candidate_specs_accepts_utf8_bom(tmp_path) -> None:
    module = _load_script_module()
    table = tmp_path / "candidates.csv"
    table.write_text(
        "\ufeffcandidate_id,mK,Sy,steady_catalog,steady_ref,transient_ref\n"
        "named,1.0,0.05,/tmp/steady.duckdb,steady_run,transient_run\n",
        encoding="utf-8",
    )

    specs = module.load_candidate_specs(table)

    assert specs[0]["candidate_id"] == "named"


def test_score_candidate_specs_ranks_completed_before_failed(monkeypatch, tmp_path) -> None:
    module = _load_script_module()
    specs = [
        {"candidate_id": "bad", "mK": "3", "Sy": "0.1"},
        {"candidate_id": "best", "mK": "1", "Sy": "0.05"},
        {"candidate_id": "ok", "mK": "2", "Sy": "0.08"},
    ]

    def fake_score_one(spec, *, truth_dir, catalog_cache):
        del truth_dir, catalog_cache
        if spec["candidate_id"] == "bad":
            return {
                "candidate_id": "bad",
                "mK": 3.0,
                "Sy": 0.1,
                "status": "failed",
                "objective": math.nan,
            }
        objective = 0.0 if spec["candidate_id"] == "best" else 1.5
        return {
            "candidate_id": spec["candidate_id"],
            "mK": float(spec["mK"]),
            "Sy": float(spec["Sy"]),
            "status": "completed",
            "objective": objective,
        }

    monkeypatch.setattr(module, "_score_one_spec", fake_score_one)

    frame = module.score_candidate_specs(specs, truth_dir=tmp_path)

    assert frame["candidate_id"].tolist() == ["best", "ok", "bad"]
    assert frame["rank"].tolist() == [1, 2, 3]


# From test_b0_synthetic_smoke.py


SCRIPT_PATH__b0_synthetic = (
    Path(__file__).resolve().parents[3]
    / "validation_cases"
    / "calibration"
    / "network_transient_b0"
    / "run_synthetic_smoke.py"
)


def _load_script_module__b0_synthetic():
    spec = importlib.util.spec_from_file_location("b0_synthetic_smoke", SCRIPT_PATH__b0_synthetic)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_synthetic_smoke_ranks_truth_candidate_first(tmp_path) -> None:
    module = _load_script_module__b0_synthetic()

    frame = module.run_synthetic_smoke(
        tmp_path,
        mK_values=[0.75, 1.0, 1.25],
        Sy_values=[0.03, 0.05, 0.08],
    )

    best = frame.iloc[0]
    assert best["mK"] == 1.0
    assert best["Sy"] == 0.05
    assert best["rank"] == 1
    assert math.isclose(float(best["objective"]), 0.0, abs_tol=1e-12)
    assert (tmp_path / "truth" / "normalization.json").exists()
    assert (tmp_path / "candidate_scores.csv").exists()
    assert (tmp_path / "summary.json").exists()


def test_synthetic_smoke_cli_writes_outputs(tmp_path, capsys) -> None:
    module = _load_script_module__b0_synthetic()

    exit_code = module.main(
        [
            "--output-dir",
            str(tmp_path),
            "--mK-values",
            "1.0,1.5",
            "--Sy-values",
            "0.05,0.12",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "best=mK_1__Sy_0.05" in captured.out
    assert (tmp_path / "candidate_scores.json").exists()
