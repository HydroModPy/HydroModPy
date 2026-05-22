"""Behavioral tests for the public display dispatcher."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import viz


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def test_show_rejects_unsupported_input_type(mpl) -> None:
    with pytest.raises(
        TypeError,
        match="xarray.DataArray, pandas.Series, or geopandas.GeoDataFrame",
    ):
        viz.show(object())


def test_show_series_plots_lttb_decimated_values(monkeypatch, mpl) -> None:
    import hydromodpy.results.timeseries_downsample as downsample

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
    import hydromodpy.results.timeseries_downsample as downsample

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
