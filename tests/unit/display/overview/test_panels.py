"""Panels of the site overview: tables, time series, monthly climate (mm) and maps.

Coordinates are in m. The tests read artists, texts, colors and legends, never pixels.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.overview import panels
from hydromodpy.display.style import themed

STATIONS = {
    "hydrometry": {
        "x": 105.0,
        "y": 195.0,
        "crs": None,
        "label": "H1",
        "marker": "o",
        "color": "white",
        "group": "Hydrometry",
    },
    # 5 km east and 5 km north of the raster, so the legend says it is off the map.
    "piezometry_far": {
        "x": 5100.0,
        "y": 5190.0,
        "crs": None,
        "label": "P1",
        "marker": "^",
        "color": "skyblue",
        "group": "Piezometry",
    },
}


def luminance(color) -> float:
    from matplotlib.colors import to_rgb

    red, green, blue = to_rgb(color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def stats_and_inventory_tables(plt):
    fig, (ax_stats, ax_inventory) = plt.subplots(1, 2)
    summary = SimpleNamespace(
        watershed_name="Naizin",
        catchment_area_km2=12.5,
        date_start="2020-01-01",
        date_end="2020-12-31",
        n_streams=3,
        n_hydrometry=1,
        n_piezometry=2,
        n_intermittency=0,
        n_water_quality=4,
    )
    inventory = [{"type": "Hydrometry", "id": "H1", "x": 1.0, "y": 2.0, "start": "a", "end": "b"}]
    panels.render_stats_card(ax_stats, summary=summary)
    panels.render_station_inventory(ax_inventory, inventory=inventory)
    return ax_stats.tables[0], ax_inventory.tables[0]


def write_dem(path, *, origin, cell_m, data):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        transform=from_origin(*origin, cell_m, cell_m),
    ) as dst:
        dst.write(np.asarray(data, dtype="float32").reshape(1, 2, 2))
    return path


def test_dark_theme_tables(mpl) -> None:
    with themed("dark"):
        tables = stats_and_inventory_tables(mpl)
    for table in tables:
        for cell in table.get_celld().values():
            assert luminance(cell.get_facecolor()) < 0.5, "a cell is still white"
            assert luminance(cell.get_text().get_color()) > 0.5, "dark text on a dark cell"
            assert luminance(cell.get_edgecolor()) < 0.5, "an edge is brighter than the text"


def test_default_theme_tables(mpl) -> None:
    with themed("default"):
        tables = stats_and_inventory_tables(mpl)
    for table in tables:
        body = table[(1, 1)]
        assert luminance(body.get_facecolor()) > 0.95
        assert luminance(body.get_text().get_color()) < 0.1


def test_outline_color() -> None:
    with themed("default"):
        assert panels._outline_color() == "#000000"
    with themed("dark"):
        assert luminance(panels._outline_color()) > 0.8


def test_timeseries_bounds_and_hlines(mpl) -> None:
    frame = pd.DataFrame(
        {"H1": [1.0, 2.0], "H2": [3.0, None]},
        index=pd.to_datetime(["2020-01-01", "2020-01-02"]),
    )
    _, ax = mpl.subplots()

    panels.render_timeseries_multi(
        ax,
        df=frame,
        ylabel="Discharge",
        unit="m3/s",
        title="Hydrometry",
        date_start="2020-01-01",
        date_end="2020-01-03",
        hlines=[{"y": 2.5, "label": "threshold", "color": "red"}],
    )

    assert len(ax.lines) == 3  # two stations and the threshold
    assert ax.get_ylabel() == "Discharge (m3/s)"
    assert ax.get_legend() is not None
    assert ax.get_xlim()[0] <= ax.convert_xunits(pd.Timestamp("2020-01-01"))
    assert ax.get_xlim()[1] >= ax.convert_xunits(pd.Timestamp("2020-01-03"))


def test_timeseries_without_records(mpl) -> None:
    _, ax = mpl.subplots()

    panels.render_timeseries_multi(ax, df=None, ylabel="Y", title="Empty")

    assert ax.texts[0].get_text() == "No records"


def test_water_quality_strip_per_parameter(mpl) -> None:
    _, ax = mpl.subplots()
    index = pd.to_datetime(["2020-01-01", "2020-01-02"])
    series_by_param = {
        "NO3": {"S1": pd.Series([1.0, 2.0], index=index)},
        "CL": {"S1": pd.Series([4.0, 5.0], index=index), "S2": pd.Series([6.0, 7.0], index=index)},
    }

    axes = panels.render_water_quality(
        ax,
        series_by_param=series_by_param,
        title="Water quality",
        date_start="2019-12-31",
        date_end="2020-01-03",
        units={"NO3": "mg(NO3)/L"},
        station_names={"S2": "La riviere"},
    )

    assert len(axes) == 2
    assert axes[0].get_ylabel() == "NO3 (mg(NO3)/L)"
    assert axes[1].get_ylabel() == "CL"
    assert [line.get_label() for line in axes[1].lines] == ["S1", "S2 La riviere"]
    assert axes[0].lines[0].get_color() == axes[1].lines[0].get_color()
    assert axes[1].lines[1].get_ydata().tolist() == [6.0, 7.0]
    assert axes[0].get_legend() is not None
    assert axes[0].get_xlim()[0] <= axes[0].convert_xunits(pd.Timestamp("2019-12-31"))


@pytest.mark.fast
def test_sampling_gap_breaks_the_line() -> None:
    # A gap of 11 months between two analyses is longer than the 120 days allowed.
    serie = pd.Series(
        [1.0, 2.0, 3.0], index=pd.to_datetime(["2020-01-01", "2020-02-01", "2021-01-01"])
    )

    broken = panels._break_gaps(serie, 120)

    assert broken.isna().sum() == 1
    assert broken.dropna().tolist() == [1.0, 2.0, 3.0]
    assert broken.index.is_monotonic_increasing


def test_climatic_summary_bars(mpl) -> None:
    _, ax = mpl.subplots()

    panels.render_climatic_summary(
        ax,
        monthly_precip=np.arange(1, 13, dtype=float),  # mm
        monthly_etp=np.full(12, 2.5),  # mm
        title="Monthly climate",
    )

    assert len(ax.patches) == 24
    assert [patch.get_height() for patch in ax.patches[:3]] == [1.0, 2.0, 3.0]
    assert [label.get_text() for label in ax.get_xticklabels()] == [
        "J",
        "F",
        "M",
        "A",
        "M",
        "J",
        "J",
        "A",
        "S",
        "O",
        "N",
        "D",
    ]
    assert ax.get_legend() is not None


def test_intermittency_strips(mpl) -> None:
    # O3 has no observation, so it gets no strip.
    _, ax = mpl.subplots()
    df = pd.DataFrame(
        {"O1": [1.0, 5.0], "O2": [np.nan, 3.0], "O3": [np.nan, np.nan]},
        index=pd.to_datetime(["2020-01-01", "2020-02-01"]),
    )

    axes = panels.render_intermittency(
        ax,
        df=df,
        title="ONDE",
        date_start="2020-01-01",
        date_end="2020-03-01",
        station_names={"O1": "Le ruisseau"},
    )

    assert len(axes) == 2
    assert [sub.get_title() for sub in axes] == ["O1 - Le ruisseau", "O2"]
    assert [tick.get_text() for tick in axes[0].get_yticklabels()] == [
        "Dry",
        "Invisible",
        "Low",
        "Acceptable",
        "Visible",
    ]
    assert axes[0].get_ylim() == pytest.approx((0.5, 5.5))
    dry, visible = axes[0].collections[0].get_facecolors()
    assert tuple(dry[:3]) == pytest.approx((0.5, 0.0, 0.0), abs=0.01)
    assert tuple(visible[:3]) == pytest.approx((0.0, 0.0, 0.5), abs=0.01)


def test_empty_station_inventory(mpl) -> None:
    _, ax = mpl.subplots()

    panels.render_station_inventory(ax, inventory=[])

    assert ax.texts[0].get_text() == "No stations loaded"
    assert not ax.axison


def test_maps_of_a_minimal_raster(tmp_path, mpl) -> None:
    dem = write_dem(tmp_path / "dem.tif", origin=(100.0, 200.0), cell_m=10.0, data=[1, 2, 3, 4])
    _, axes = mpl.subplots(1, 3)

    panels.render_dem_map(
        axes[0],
        dem_path=str(dem),
        station_points=list(STATIONS.values()),
        title="DEM",
    )
    panels.render_hydrography_map(
        axes[1], dem_path=str(dem), outlet_xy=(105.0, 195.0), title="Hydro"
    )
    panels.render_geology_map(axes[2], dem_path=str(dem), title="Geo")

    assert axes[0].get_title() == "DEM"
    legend = axes[0].get_legend()
    assert [text.get_text() for text in legend.get_texts()] == [
        "Hydrometry",
        "Piezometry (off map, 7 km NE)",
    ]
    assert axes[1].lines[0].get_marker() == "*"
    assert axes[2].get_title() == "Geo"
    assert all(axis.get_aspect() == 1.0 for axis in axes)


def test_regional_context_map(tmp_path, mpl) -> None:
    # Two 10 km cells, upper left corner at (0, 20000) m.
    dem = write_dem(tmp_path / "regional.tif", origin=(0.0, 20000.0), cell_m=10000.0, data=[1] * 4)
    _, ax = mpl.subplots()

    panels.render_regional_context_map(
        ax,
        regional_dem_path=str(dem),
        station_points=[
            {"x": 15000.0, "y": 18000.0, "crs": None, "marker": "^", "group": "Piezometry"}
        ],
        title="Regional",
    )

    assert ax.collections[-1].get_offsets().tolist() == [[15000.0, 18000.0]]
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert labels == ["Catchment", "Piezometry"]
