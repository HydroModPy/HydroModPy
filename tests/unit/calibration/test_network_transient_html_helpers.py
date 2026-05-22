from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import hydromodpy.calibration.reporting.network_transient_html as report


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
        == "moyenne transitoire"
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
        "reference synthetique": [9.0],
        "candidate": [1.5, 2.5],
    }


def test_mesh_context_from_truth_package_uses_bundle_and_outlet_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report, "PATH_BASE", tmp_path)
    config = tmp_path / "source.toml"
    config.write_text("[geographic]\nx_outlet = 10.0\ny_outlet = 20.0\n", encoding="utf-8")
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
