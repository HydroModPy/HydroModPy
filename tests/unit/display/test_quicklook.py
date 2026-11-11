"""The quicklook viewer: scalable display, show dispatch and animation builders."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.quicklook import scalable, viz
from hydromodpy.display.quicklook.animation import build_gif, build_mp4, build_plotly_slider

# Unit tests for the scalable rasterization helpers.
#
# Covers ``hydromodpy.display.quicklook.scalable``:
# - threshold detection (``should_rasterize``)
# - datashader availability probe
# - 2D xr.DataArray rasterization to a target pixel resolution
# - point cloud rasterization (centroids of an unstructured mesh)
# - early-return when the mesh is below threshold


def test_should_rasterize_threshold_returns_true_above_default() -> None:
    assert scalable.should_rasterize(200_000) is True


def test_should_rasterize_threshold_returns_false_below_default() -> None:
    assert scalable.should_rasterize(50_000) is False


def test_should_rasterize_custom_threshold() -> None:
    assert scalable.should_rasterize(1000, threshold=500) is True
    assert scalable.should_rasterize(100, threshold=500) is False


def test_rasterize_field_downsamples_dense_grid_to_target_px() -> None:
    """rasterize_field must reduce a grid coarser than the target and keep it finite.

    ``rasterize_field`` never consults ``DEFAULT_CELL_THRESHOLD`` itself (that
    threshold only gates the caller's decision to rasterize at all, via
    ``should_rasterize``), so the input only needs to be larger than
    ``target_px`` on both axes to exercise the datashader downsampling path.
    A 100x100 grid downsampled to 50x30 is enough and runs in milliseconds,
    against ~3s for the previous 1000x1000 grid.
    """
    pytest.importorskip("datashader")
    pytest.importorskip("xarray")
    import xarray as xr

    side = 100
    rng = np.random.default_rng(seed=42)
    data = rng.random((side, side)).astype("float32")
    da = xr.DataArray(
        data,
        coords={"y": np.linspace(0.0, 100.0, side), "x": np.linspace(0.0, 100.0, side)},
        dims=("y", "x"),
        name="head",
    )
    out = scalable.rasterize_field(da, target_px=(50, 30))
    assert tuple(out.shape) == (30, 50)
    values = out.values
    assert np.isfinite(values).all(), "downsampled raster must have no NaN pixel"
    # Mean aggregation of source data in [0, 1) cannot produce values outside it.
    assert values.min() >= 0.0
    assert values.max() < 1.0


def test_rasterize_field_below_threshold_no_downsample() -> None:
    """A field below the threshold needs no rasterization at the API level."""
    # The helper does not auto-skip; we verify the threshold logic instead.
    n_cells = 10_000  # Below the default 100k threshold.
    assert scalable.should_rasterize(n_cells) is False


def test_rasterize_field_rejects_zero_dimensions() -> None:
    import xarray as xr

    da = xr.DataArray(
        np.zeros((4, 4)),
        coords={"y": np.arange(4), "x": np.arange(4)},
        dims=("y", "x"),
    )
    with pytest.raises(ValueError):
        scalable.rasterize_field(da, target_px=(0, 100))


def test_rasterize_field_rejects_unknown_agg() -> None:
    import xarray as xr

    da = xr.DataArray(
        np.zeros((4, 4)),
        coords={"y": np.arange(4), "x": np.arange(4)},
        dims=("y", "x"),
    )
    with pytest.raises(ValueError):
        scalable.rasterize_field(da, target_px=(8, 8), agg="median")


def test_is_datashader_available_consistent_with_import() -> None:
    """The probe should mirror whether the optional extra is installed."""
    available = scalable.is_datashader_available()
    try:
        import datashader  # noqa: F401

        installed = True
    except ImportError:
        installed = False
    assert available is installed


# Behavioral tests for the public display dispatcher.


def test_show_rejects_unsupported_input_type(mpl) -> None:
    with pytest.raises(
        TypeError,
        match="xarray.DataArray, pandas.Series, or geopandas.GeoDataFrame",
    ):
        viz.show(object())


def test_show_series_plots_lttb_decimated_values(monkeypatch, mpl) -> None:
    import hydromodpy.results.derive.downsample as downsample

    series = pd.Series(
        [10.0, 12.0, 8.0, 11.0],
        index=pd.date_range("2020-01-01", periods=4, freq="D"),
        name="discharge",
    )
    calls: dict[str, object] = {}

    def _fake_lttb(input_series: pd.Series, *, n_out: int) -> pd.Series:
        calls["series"] = input_series
        calls["n_out"] = n_out
        return input_series.iloc[[0, -1]]

    monkeypatch.setattr(downsample, "lttb_downsample", _fake_lttb)

    fig = viz.show(
        series,
        downsample="lttb",
        n_out=2,
        color="tab:red",
        linewidth=2.5,
    )

    try:
        assert calls == {"series": series, "n_out": 2}
        line = fig.axes[0].lines[0]
        assert line.get_ydata().tolist() == [10.0, 11.0]
        assert line.get_color() == "tab:red"
        assert line.get_linewidth() == 2.5
    finally:
        mpl.close(fig)


def test_show_series_auto_keeps_small_series_without_lttb(monkeypatch, mpl) -> None:
    import hydromodpy.results.derive.downsample as downsample

    series = pd.Series(
        [1.0, 2.0, 3.0],
        index=pd.date_range("2020-02-01", periods=3, freq="D"),
        name="head",
    )

    monkeypatch.setattr(downsample, "should_downsample", lambda *_args, **_kwargs: False)

    def _raise_lttb(*_args, **_kwargs) -> pd.Series:
        raise AssertionError("LTTB should not run for a small auto series")

    monkeypatch.setattr(downsample, "lttb_downsample", _raise_lttb)

    fig = viz.show(series, downsample="auto", marker="o")

    try:
        line = fig.axes[0].lines[0]
        assert line.get_ydata().tolist() == [1.0, 2.0, 3.0]
        assert line.get_marker() == "o"
    finally:
        mpl.close(fig)


def test_show_dataarray_without_raster_preserves_values_and_crs_title(mpl) -> None:
    xr = pytest.importorskip("xarray")

    data = np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    da = xr.DataArray(
        data,
        coords={"y": [0.0, 1.0], "x": [10.0, 11.0, 12.0]},
        dims=("y", "x"),
        name="head",
    )

    fig = viz.show(da, downsample="none", crs="EPSG:2154", cmap="viridis")

    try:
        ax = fig.axes[0]
        assert ax.get_title() == "CRS: EPSG:2154"
        assert np.asarray(ax.images[0].get_array()).tolist() == data.tolist()
        assert ax.images[0].get_cmap().name == "viridis"
    finally:
        mpl.close(fig)


# Tests for animation builders that create user-facing files.


def _write_png(path: Path, color: tuple[int, int, int]) -> None:
    image = pytest.importorskip("PIL.Image")
    image.new("RGB", (4, 3), color).save(path)


def test_build_gif_returns_none_for_empty_frame_list(tmp_path) -> None:
    out = tmp_path / "empty.gif"

    assert build_gif(frame_paths=[], gif_path=out) is None
    assert not out.exists()


def test_build_gif_writes_all_frames_and_duration(tmp_path) -> None:
    image = pytest.importorskip("PIL.Image")
    frame_a = tmp_path / "frame_a.png"
    frame_b = tmp_path / "frame_b.png"
    _write_png(frame_a, (255, 0, 0))
    _write_png(frame_b, (0, 0, 255))
    out = tmp_path / "movie.gif"

    result = build_gif(frame_paths=[frame_a, frame_b], gif_path=out, duration_ms=123)

    assert result == out
    assert out.exists()
    with image.open(out) as gif:
        assert gif.n_frames == 2
        assert abs(gif.info["duration"] - 123) <= 10


def test_build_mp4_returns_none_for_empty_frame_list(tmp_path) -> None:
    out = tmp_path / "empty.mp4"

    assert build_mp4(frame_paths=[], mp4_path=out) is None
    assert not out.exists()


def test_build_plotly_slider_writes_embedded_frame_html(tmp_path) -> None:
    pytest.importorskip("plotly.graph_objects")
    frame_a = tmp_path / "frame_a.png"
    frame_b = tmp_path / "frame_b.png"
    _write_png(frame_a, (10, 20, 30))
    _write_png(frame_b, (40, 50, 60))
    out = tmp_path / "nested" / "slider.html"

    result = build_plotly_slider(
        frame_paths=[frame_a, frame_b],
        html_path=out,
        show_in_browser=False,
        title="Observed heads",
    )

    html = out.read_text(encoding="utf-8")
    assert result == out
    assert "Observed heads" in html
    assert html.count("data:image/png;base64") >= 2
