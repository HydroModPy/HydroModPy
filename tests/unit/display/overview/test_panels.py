"""Panels of the site overview: tables, time series, monthly climate (mm) and maps.

Coordinates are in m. The tests read the data a panel shows and the global state it leaves.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import matplotlib
import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_rgb

from hydromodpy.display.overview import panels
from hydromodpy.display.static import new_figure
from hydromodpy.display.theme import get_theme

THEME = get_theme("default")
DATES = pd.to_datetime(["2020-01-01", "2020-02-01"])
SUMMARY = SimpleNamespace(
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
STATION = {"x": 105.0, "y": 195.0, "crs": "EPSG:2154", "marker": "o", "group": "Hydrometry"}
# 5 km east and 5 km north of the raster, so the legend says it is off the map.
FAR = {"x": 5100.0, "y": 5190.0, "crs": "EPSG:2154", "marker": "^", "group": "Piezometry"}


def draw(render, **kwargs):
    """Draw one panel on a fresh figure and return the result."""
    return render(new_figure(THEME).axes[0], theme=THEME, **kwargs)


def write_dem(path, *, origin, cell_m, data):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.crs import CRS
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs=CRS.from_epsg(2154),
        transform=from_origin(*origin, cell_m, cell_m),
    ) as dst:
        dst.write(np.asarray(data, dtype="float32").reshape(1, 2, 2))
    return path


def test_tables_show_their_rows_in_the_theme() -> None:
    inventory = [{"type": "Hydrometry", "id": "H1", "x": 1.0, "y": 2.0, "start": "a", "end": "b"}]
    stats = draw(panels.render_stats_card, summary=SUMMARY).tables[0]
    listing = draw(panels.render_station_inventory, inventory=inventory).tables[0]

    assert stats[(0, 1)].get_text().get_text() == "Naizin"
    assert stats[(1, 1)].get_text().get_text() == "12.50 km²"
    assert listing[(1, 1)].get_text().get_text() == "H1"
    assert listing[(0, 0)].get_facecolor()[:3] == pytest.approx(to_rgb(THEME.roles["no_data"]))
    for cell in [*stats.get_celld().values(), *listing.get_celld().values()]:
        assert cell.get_text().get_fontfamily() == [THEME.family]
        assert cell.get_edgecolor()[:3] == pytest.approx(to_rgb(THEME.muted))


def test_empty_station_inventory() -> None:
    ax = draw(panels.render_station_inventory, inventory=[])

    assert [text.get_text() for text in ax.texts] == ["No stations loaded"]
    assert not ax.axison


def test_timeseries_lines_hlines_and_bounds() -> None:
    frame = pd.DataFrame({"H1": [1.0, 2.0], "H2": [3.0, None]}, index=DATES[:2])
    ax = draw(
        panels.render_timeseries_multi,
        df=frame,
        ylabel="Discharge",
        unit="m3/s",
        title="Hydrometry",
        date_start="2020-01-01",
        date_end="2020-03-01",
        hlines=[{"y": 2.5, "label": "threshold"}],
    )

    assert [line.get_ydata().tolist() for line in ax.lines[:2]] == [[1.0, 2.0], [3.0]]
    assert list(ax.lines[2].get_ydata()) == [2.5, 2.5]
    assert ax.lines[0].get_color() == THEME.categorical[0]
    assert ax.lines[2].get_color() == THEME.roles["observed"]
    assert ax.get_ylabel() == "Discharge (m3/s)"
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["H1", "H2", "threshold"]
    assert ax.get_xlim()[1] == pytest.approx(ax.convert_xunits(pd.Timestamp("2020-03-01")))


def test_timeseries_without_records() -> None:
    ax = draw(panels.render_timeseries_multi, df=None, ylabel="Y", title="Empty")

    assert ax.texts[0].get_text() == "No records"
    assert ax.get_title() == "Empty"


def test_water_quality_strip_per_parameter() -> None:
    series_by_param = {
        "NO3": {"S1": pd.Series([1.0, 2.0], index=DATES)},
        "CL": {"S1": pd.Series([4.0, 5.0], index=DATES), "S2": pd.Series([6.0, 7.0], index=DATES)},
    }

    axes = draw(
        panels.render_water_quality,
        series_by_param=series_by_param,
        title="Water quality",
        units={"NO3": "mg(NO3)/L"},
        station_names={"S2": "La riviere"},
    )

    assert [ax.get_ylabel() for ax in axes] == ["NO3 (mg(NO3)/L)", "CL"]
    assert [line.get_label() for line in axes[1].lines] == ["S1", "S2 La riviere"]
    assert axes[0].lines[0].get_color() == axes[1].lines[0].get_color() == THEME.categorical[0]
    assert axes[1].lines[1].get_ydata().tolist() == [6.0, 7.0]
    assert axes[0].get_legend() is not None


def test_sampling_gap_breaks_the_line() -> None:
    # A gap of 11 months between two analyses is longer than the 120 days allowed.
    dates = pd.to_datetime(["2020-01-01", "2020-02-01", "2021-01-01"])

    broken = panels._break_gaps(pd.Series([1.0, 2.0, 3.0], index=dates), 120)

    assert broken.isna().sum() == 1
    assert broken.dropna().tolist() == [1.0, 2.0, 3.0]


def test_climatic_summary_bars() -> None:
    ax = draw(
        panels.render_climatic_summary,
        monthly_precip=np.arange(1, 13, dtype=float),  # mm
        monthly_etp=np.full(12, 2.5),  # mm
    )

    assert [patch.get_height() for patch in ax.patches] == [*range(1, 13), *[2.5] * 12]
    assert ax.patches[0].get_facecolor()[:3] == pytest.approx(to_rgb(THEME.roles["inflow"]))
    assert "".join(label.get_text() for label in ax.get_xticklabels()) == "JFMAMJJASOND"
    assert ax.get_legend() is not None


def test_climatic_summary_without_data() -> None:
    ax = draw(panels.render_climatic_summary, monthly_precip=None, monthly_etp=None)

    assert [text.get_text() for text in ax.texts] == ["No climate data"]


def test_intermittency_strips() -> None:
    # O3 has no observation, so it gets no strip.
    df = pd.DataFrame({"O1": [1.0, 5.0], "O2": [np.nan, 3.0], "O3": [np.nan, np.nan]}, index=DATES)

    axes = draw(
        panels.render_intermittency, df=df, title="ONDE", station_names={"O1": "Le ruisseau"}
    )

    assert [sub.get_title() for sub in axes] == ["O1 - Le ruisseau", "O2"]
    assert [t.get_text() for t in axes[0].get_yticklabels()][::4] == ["Dry", "Visible"]
    assert axes[0].collections[0].get_offsets()[:, 1].tolist() == [1.0, 5.0]
    dry, visible = axes[0].collections[0].get_facecolors()
    assert tuple(dry[:3]) == pytest.approx((0.5, 0.0, 0.0), abs=0.01)
    assert tuple(visible[:3]) == pytest.approx((0.0, 0.0, 0.5), abs=0.01)
    assert axes[0].figure.get_suptitle() == "ONDE"


def test_maps_of_a_minimal_raster(tmp_path) -> None:
    dem = write_dem(tmp_path / "dem.tif", origin=(100.0, 200.0), cell_m=10.0, data=[1, 2, 3, 4])

    dem_map = draw(panels.render_dem_map, dem_path=str(dem), station_points=[STATION, FAR])
    hydro = draw(panels.render_hydrography_map, dem_path=str(dem), outlet_xy=(105.0, 195.0))
    geo = draw(panels.render_geology_map, dem_path=str(dem), title="Geo")

    assert dem_map.get_title() == "DEM"
    assert [t.get_text() for t in dem_map.get_legend().get_texts()] == [
        "Hydrometry",
        "Piezometry (off map, 7 km NE)",
    ]
    assert dem_map.images[0].get_array().tolist() == [[1, 2], [3, 4]]
    assert dem_map.images[0].get_cmap().name == THEME.quantity_ramps["elevation"]
    assert dem_map.get_xlabel() == "x (Lambert-93, km)"
    assert hydro.lines[0].get_xydata().tolist() == [[105.0, 195.0]]
    assert (geo.get_title(), geo.get_xlim(), geo.get_aspect()) == ("Geo", (100.0, 120.0), 1.0)


def test_geology_classes_get_a_legend(tmp_path) -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    dem = write_dem(tmp_path / "dem.tif", origin=(100.0, 200.0), cell_m=10.0, data=[1, 2, 3, 4])
    geology = gpd.GeoDataFrame(
        {"CODE_LEG": ["b", "a"]}, geometry=[box(100, 180, 110, 190), box(110, 180, 120, 190)]
    )

    ax = draw(panels.render_geology_map, dem_path=str(dem), geology_gdf=geology)

    legend = ax.figure.legends[0]
    assert [t.get_text() for t in legend.get_texts()] == ["a", "b"]
    assert legend.get_title().get_text() == "CODE_LEG"


def test_regional_context_map(tmp_path) -> None:
    # Two 10 km cells, upper left corner at (0, 20000) m.
    dem = write_dem(tmp_path / "regional.tif", origin=(0.0, 20000.0), cell_m=10000.0, data=[1] * 4)
    station = {"x": 15000.0, "y": 18000.0, "crs": "EPSG:2154", "marker": "^", "group": "Piezometry"}

    ax = draw(
        panels.render_regional_context_map,
        regional_dem_path=str(dem),
        station_points=[station],
        title="Regional",
    )

    assert ax.collections[-1].get_offsets().tolist() == [[15000.0, 18000.0]]
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["Catchment", "Piezometry"]


def test_panels_leave_no_global_state(tmp_path) -> None:
    dem = write_dem(tmp_path / "dem.tif", origin=(100.0, 200.0), cell_m=10.0, data=[1, 2, 3, 4])
    frame = pd.DataFrame({"H1": [1.0, 2.0]}, index=DATES)
    before = dict(dict.items(matplotlib.rcParams))

    def one(kind: int):
        if kind:
            ax = draw(panels.render_timeseries_multi, df=frame, ylabel="Q", title="Q")
            return ax.lines[0].get_ydata().tolist()
        return draw(panels.render_dem_map, dem_path=str(dem)).images[0].get_array().tolist()

    with ThreadPoolExecutor(2) as pool:
        series, relief = pool.map(one, [1, 0])

    assert (series, relief) == ([1.0, 2.0], [[1, 2], [3, 4]])
    assert dict(dict.items(matplotlib.rcParams)) == before
