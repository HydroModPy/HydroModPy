"""Quicklook viewer: rasterization above a cell count, the show dispatcher, animations.

``scalable`` thins a field to a target pixel grid when a mesh holds more than
the cell threshold, ``viz.show`` draws a series or a raster with a few options,
and ``animation`` assembles frame PNG files into a GIF, MP4 or HTML slider.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.quicklook import scalable, viz
from hydromodpy.display.quicklook.animation import build_gif, build_mp4, build_plotly_slider


def zero_raster(n: int = 4):
    xr = pytest.importorskip("xarray")
    return xr.DataArray(
        np.zeros((n, n)), coords={"y": np.arange(n), "x": np.arange(n)}, dims=("y", "x")
    )


def write_png(path: Path, color: tuple[int, int, int]) -> None:
    image = pytest.importorskip("PIL.Image")
    image.new("RGB", (4, 3), color).save(path)


@pytest.mark.parametrize(
    ("n_cells", "expected"),
    [
        pytest.param(200_000, True, id="above the default threshold"),
        pytest.param(50_000, False, id="below the default threshold"),
    ],
)
def test_should_rasterize(n_cells, expected) -> None:
    assert scalable.should_rasterize(n_cells) is expected


def test_rasterize_field_downsamples_to_target_pixels() -> None:
    # The grid only has to be larger than target_px on both axes to reach the
    # datashader path. 100 x 100 down to 50 x 30 runs in milliseconds.
    pytest.importorskip("datashader")
    xr = pytest.importorskip("xarray")
    side = 100
    data = np.random.default_rng(seed=42).random((side, side)).astype("float32")
    field = xr.DataArray(
        data,
        coords={"y": np.linspace(0.0, 100.0, side), "x": np.linspace(0.0, 100.0, side)},
        dims=("y", "x"),
        name="head",
    )

    out = scalable.rasterize_field(field, target_px=(50, 30))

    assert tuple(out.shape) == (30, 50)
    assert np.isfinite(out.values).all()
    # A mean of values in [0, 1) stays in [0, 1).
    assert out.values.min() >= 0.0
    assert out.values.max() < 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"target_px": (0, 100)}, id="zero dimension"),
        pytest.param({"target_px": (8, 8), "agg": "median"}, id="unknown aggregation"),
    ],
)
def test_rasterize_field_refusals(kwargs) -> None:
    with pytest.raises(ValueError):
        scalable.rasterize_field(zero_raster(), **kwargs)


def test_datashader_probe_mirrors_the_import() -> None:
    try:
        import datashader  # noqa: F401

        installed = True
    except ImportError:
        installed = False

    assert scalable.is_datashader_available() is installed


def test_show_refuses_an_unsupported_type(mpl) -> None:
    with pytest.raises(
        TypeError, match="xarray.DataArray, pandas.Series, or geopandas.GeoDataFrame"
    ):
        viz.show(object())


def test_show_series_plots_lttb_values(monkeypatch, mpl) -> None:
    import hydromodpy.results.derive.downsample as downsample

    series = pd.Series(
        [10.0, 12.0, 8.0, 11.0],
        index=pd.date_range("2020-01-01", periods=4, freq="D"),
        name="discharge",
    )
    calls: dict[str, object] = {}

    def fake_lttb(input_series: pd.Series, *, n_out: int) -> pd.Series:
        calls["series"] = input_series
        calls["n_out"] = n_out
        return input_series.iloc[[0, -1]]

    monkeypatch.setattr(downsample, "lttb_downsample", fake_lttb)

    fig = viz.show(series, downsample="lttb", n_out=2, color="tab:red", linewidth=2.5)

    assert calls == {"series": series, "n_out": 2}
    line = fig.axes[0].lines[0]
    assert line.get_ydata().tolist() == [10.0, 11.0]
    assert line.get_color() == "tab:red"
    assert line.get_linewidth() == 2.5


def test_show_small_series_skips_lttb_in_auto_mode(monkeypatch, mpl) -> None:
    import hydromodpy.results.derive.downsample as downsample

    series = pd.Series(
        [1.0, 2.0, 3.0], index=pd.date_range("2020-02-01", periods=3, freq="D"), name="head"
    )

    def lttb_must_not_run(*_args, **_kwargs) -> pd.Series:
        raise AssertionError("LTTB should not run for a small auto series")

    monkeypatch.setattr(downsample, "should_downsample", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(downsample, "lttb_downsample", lttb_must_not_run)

    fig = viz.show(series, downsample="auto", marker="o")

    line = fig.axes[0].lines[0]
    assert line.get_ydata().tolist() == [1.0, 2.0, 3.0]
    assert line.get_marker() == "o"


def test_show_refuses_a_per_cell_field_and_names_run_figure(mpl) -> None:
    xr = pytest.importorskip("xarray")
    per_cell = xr.DataArray(np.zeros(5), dims=("cell",), name="head")

    with pytest.raises(TypeError, match=r'run\.figure\("head"\)'):
        viz.show(per_cell)


def test_show_draws_a_two_dimensional_regular_array(mpl) -> None:
    xr = pytest.importorskip("xarray")
    grid = xr.DataArray(np.ones((3, 4)), dims=("y", "x"), name="head")

    fig = viz.show(grid, downsample="none")

    assert fig.axes[0].images[0].get_array().shape == (3, 4)


def test_show_raster_keeps_values_and_names_the_crs(mpl) -> None:
    xr = pytest.importorskip("xarray")
    data = np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    field = xr.DataArray(
        data, coords={"y": [0.0, 1.0], "x": [10.0, 11.0, 12.0]}, dims=("y", "x"), name="head"
    )

    fig = viz.show(field, downsample="none", crs="EPSG:2154", cmap="viridis")

    ax = fig.axes[0]
    assert ax.get_title() == "CRS: EPSG:2154"
    assert np.asarray(ax.images[0].get_array()).tolist() == data.tolist()
    assert ax.images[0].get_cmap().name == "viridis"


def test_build_gif_without_frames_writes_nothing(tmp_path) -> None:
    out = tmp_path / "empty.gif"

    assert build_gif(frame_paths=[], gif_path=out) is None
    assert not out.exists()


def test_build_gif_writes_every_frame_with_its_duration(tmp_path) -> None:
    image = pytest.importorskip("PIL.Image")
    frame_a, frame_b = tmp_path / "frame_a.png", tmp_path / "frame_b.png"
    write_png(frame_a, (255, 0, 0))
    write_png(frame_b, (0, 0, 255))
    out = tmp_path / "movie.gif"

    result = build_gif(frame_paths=[frame_a, frame_b], gif_path=out, duration_ms=123)

    assert result == out
    with image.open(out) as gif:
        assert gif.n_frames == 2
        assert abs(gif.info["duration"] - 123) <= 10


def test_build_mp4_without_frames_writes_nothing(tmp_path) -> None:
    out = tmp_path / "empty.mp4"

    assert build_mp4(frame_paths=[], mp4_path=out) is None
    assert not out.exists()


def test_build_plotly_slider_embeds_the_frames(tmp_path) -> None:
    pytest.importorskip("plotly.graph_objects")
    frame_a, frame_b = tmp_path / "frame_a.png", tmp_path / "frame_b.png"
    write_png(frame_a, (10, 20, 30))
    write_png(frame_b, (40, 50, 60))
    out = tmp_path / "nested" / "slider.html"

    result = build_plotly_slider(
        frame_paths=[frame_a, frame_b], html_path=out, show_in_browser=False, title="Observed heads"
    )

    html = out.read_text(encoding="utf-8")
    assert result == out
    assert "Observed heads" in html
    assert html.count("data:image/png;base64") >= 2
