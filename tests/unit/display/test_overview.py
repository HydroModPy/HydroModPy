"""The overview: config window, theme, helpers, report panels, attempt protocol and web blocks."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

import hydromodpy.workflow.overview as overview_module
from hydromodpy.display.overview import panels, report
from hydromodpy.display.overview.config import OverviewConfig
from hydromodpy.display.overview.location import (
    overview_figures_dir,
    overview_run_dir,
    overview_run_dir_of,
)
from hydromodpy.display.overview.panels import render_timeseries_multi
from hydromodpy.display.overview.report import _piezo_altitude_hlines, _records_to_timeseries_df
from hydromodpy.display.overview.summary import compute_overview_summary, station_table
from hydromodpy.display.style import themed
from hydromodpy.project.dispatch.workflow import run_overview
from hydromodpy.project.request import request_of
from hydromodpy.results.outcome import effective_status, read_outcome

# ``[overview]`` is the date declaration of overview mode, so it validates like one.


@pytest.mark.parametrize(
    ("declared", "missing"),
    [
        ({"date_start": "2019-01-01"}, "date_end"),
        ({"date_end": "2025-12-31"}, "date_start"),
    ],
)
def test_half_declared_window_is_rejected(declared: dict[str, str], missing: str) -> None:
    with pytest.raises(ValidationError, match=f"overview.{missing} is missing"):
        OverviewConfig(**declared)


def test_reversed_window_is_rejected() -> None:
    with pytest.raises(ValidationError, match="overview.date_start must be before"):
        OverviewConfig(date_start="2025-12-31", date_end="2019-01-01")


def test_non_iso_date_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Invalid ISO date"):
        OverviewConfig(date_start="01-01-2019", date_end="2025-12-31")


# The overview tables and the catchment outline follow the dark theme of the figures.


def _luminance(color) -> float:
    from matplotlib.colors import to_rgb

    red, green, blue = to_rgb(color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _tables(plt):
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
    inventory = [
        {"type": "Hydrometry", "id": "H1", "x": 1.0, "y": 2.0, "start": "a", "end": "b"},
    ]
    panels.render_stats_card(ax_stats, summary=summary)
    panels.render_station_inventory(ax_inventory, inventory=inventory)
    return ax_stats.tables[0], ax_inventory.tables[0]


def test_the_tables_are_drawn_on_the_dark_background_in_the_dark_theme(mpl) -> None:
    with themed("dark"):
        tables = _tables(mpl)
    for table in tables:
        for cell in table.get_celld().values():
            assert _luminance(cell.get_facecolor()) < 0.5, "a cell is still white"
            assert _luminance(cell.get_text().get_color()) > 0.5, "dark text on a dark cell"
            assert _luminance(cell.get_edgecolor()) < 0.5, "an edge is brighter than the text"


def test_the_tables_keep_white_cells_in_the_default_theme(mpl) -> None:
    with themed("default"):
        tables = _tables(mpl)
    for table in tables:
        body = table[(1, 1)]
        assert _luminance(body.get_facecolor()) > 0.95
        assert _luminance(body.get_text().get_color()) < 0.1


def test_the_catchment_outline_is_black_on_light_and_light_on_dark() -> None:
    with themed("default"):
        assert panels._outline_color() == "#000000"
    with themed("dark"):
        assert _luminance(panels._outline_color()) > 0.8


# Unit tests for overview data transformations and panels.


def _record(
    station_id: str,
    *,
    variable: str = "discharge",
    values: list[float] | None = None,
    dates: list[str] | None = None,
    altitude: object = None,
    date_start: str | None = None,
    date_end: str | None = None,
):
    frame = None
    if values is not None:
        frame = pd.DataFrame(
            {
                "datetime": pd.to_datetime(dates or ["2020-01-02", "2020-01-01"]),
                "value": values,
            }
        )
    metadata = {} if altitude is None else {"altitude": altitude}
    return SimpleNamespace(
        station_id=station_id,
        variable=variable,
        data=frame,
        location=SimpleNamespace(x=1.0, y=2.0, crs="EPSG:2154", metadata=metadata),
        date_start=pd.Timestamp(date_start) if date_start else None,
        date_end=pd.Timestamp(date_end) if date_end else None,
    )


def test_records_to_timeseries_df_sorts_dates_and_ignores_empty_records() -> None:
    df = _records_to_timeseries_df(
        [
            _record("H1", values=[2.0, 1.0]),
            _record("H2", values=[4.0, 3.0], dates=["2020-01-03", "2020-01-01"]),
            _record("empty"),
        ]
    )

    assert list(df.index) == list(pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]))
    assert df["H1"].tolist() == [1.0, 2.0, pytest.approx(float("nan"), nan_ok=True)]
    assert df.loc[pd.Timestamp("2020-01-03"), "H2"] == 4.0
    assert _records_to_timeseries_df([]) is None


def test_piezo_altitude_hlines_keep_valid_station_altitudes_only() -> None:
    hlines = _piezo_altitude_hlines(
        [
            _record("P1", altitude="42.5"),
            _record("P2", altitude="bad"),
            SimpleNamespace(station_id="P3", location=None),
        ]
    )

    assert hlines == [
        {
            "y": 42.5,
            "label": "P1 ground (42.5 m)",
            "color": "darkred",
            "linestyle": "--",
        }
    ]


def _station(family: str, item_id: str, first: str | None, last: str | None, **extra):
    row = {
        "row_kind": "station",
        "family": family,
        "item_id": item_id,
        "x": 1.0,
        "y": 2.0,
        "first": None if first is None else pd.Timestamp(first, tz="UTC"),
        "last": None if last is None else pd.Timestamp(last, tz="UTC"),
    }
    row.update(extra)
    return row


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        pytest.param(
            [
                {"row_kind": "family", "family": "hydrometry", "item_id": ""},
                _station("hydrometry", "H1", "2020-01-02", "2020-01-03"),
                _station("water_quality", "WQ1", "2020-01-01", "2020-03-01"),
            ],
            [
                {
                    "type": "Hydrometry",
                    "id": "H1",
                    "x": 1.0,
                    "y": 2.0,
                    "start": "2020-01-02",
                    "end": "2020-01-03",
                },
                {
                    "type": "Water quality",
                    "id": "WQ1",
                    "x": 1.0,
                    "y": 2.0,
                    "start": "2020-01-01",
                    "end": "2020-03-01",
                },
            ],
            id="stations-only-with-day-text",
        ),
        pytest.param(
            [_station("piezometry", "P1", None, None, x=None, y=None)],
            [{"type": "Piezometry", "id": "P1", "x": None, "y": None, "start": "", "end": ""}],
            id="no-location-no-period",
        ),
        pytest.param(
            [{"row_kind": "well", "family": "pumping", "item_id": "w"}], [], id="no-station"
        ),
    ],
)
def test_station_table_lists_the_station_rows_of_the_inventory(rows, expected) -> None:
    assert station_table(rows) == expected


def test_render_timeseries_multi_applies_bounds_hlines_and_empty_states() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frame = pd.DataFrame(
        {"H1": [1.0, 2.0], "H2": [3.0, None]},
        index=pd.to_datetime(["2020-01-01", "2020-01-02"]),
    )
    fig, ax = plt.subplots()
    render_timeseries_multi(
        ax,
        df=frame,
        ylabel="Discharge",
        unit="m3/s",
        title="Hydrometry",
        date_start="2020-01-01",
        date_end="2020-01-03",
        hlines=[{"y": 2.5, "label": "threshold", "color": "red"}],
    )

    try:
        assert len(ax.lines) == 3
        assert ax.get_ylabel() == "Discharge (m3/s)"
        assert ax.get_legend() is not None
        assert ax.get_xlim()[0] <= ax.convert_xunits(pd.Timestamp("2020-01-01"))
        assert ax.get_xlim()[1] >= ax.convert_xunits(pd.Timestamp("2020-01-03"))
    finally:
        plt.close(fig)

    fig, ax = plt.subplots()
    render_timeseries_multi(ax, df=None, ylabel="Y", title="Empty")
    try:
        assert ax.texts[0].get_text() == "No records"
    finally:
        plt.close(fig)


def test_compute_overview_summary_counts_loaded_records_and_dates() -> None:
    loaded = SimpleNamespace(
        hydrometry=SimpleNamespace(points=[_record("H1"), _record("H2")]),
        piezometry=SimpleNamespace(points=[_record("P1")]),
        intermittency=None,
        water_quality=SimpleNamespace(points=[_record("WQ1"), _record("WQ2")]),
        hydrography=SimpleNamespace(
            fields=[SimpleNamespace(metadata={"vector_path": "/missing.gpkg"})]
        ),
    )
    inventory = [
        _station("hydrometry", "H1", None, None),
        _station("hydrometry", "H2", None, None),
        _station("piezometry", "P1", None, None),
        _station("water_quality", "WQ1", None, None),
        _station("water_quality", "WQ2", None, None),
    ]
    state = SimpleNamespace(
        loaded_data=loaded,
        domain_geographic=SimpleNamespace(
            catchment_area_km2=12.5,
            x_outlet=1.25,
            y_outlet=2.5,
        ),
        cfg=SimpleNamespace(
            overview=SimpleNamespace(
                name="Naizin",
                date_start="2020-01-01",
                date_end="2020-12-31",
            )
        ),
        workspace=None,
    )

    summary = compute_overview_summary(state, inventory)

    assert summary.watershed_name == "Naizin"
    assert summary.catchment_area_km2 == 12.5
    assert summary.outlet_xy == (1.25, 2.5)
    assert summary.n_hydrometry == 2
    assert summary.n_piezometry == 1
    assert summary.n_water_quality == 2
    assert summary.n_streams == 0
    assert summary.date_start == "2020-01-01"


# Behavioral tests for overview report conversions and panels.


def _point_record(
    station_id: str,
    *,
    variable: str | None = "discharge",
    values: list[float] | None = None,
    dates: list[str] | None = None,
    columns: dict[str, object] | None = None,
):
    data = None
    if values is not None:
        data = pd.DataFrame(
            {
                "datetime": pd.to_datetime(dates or ["2020-01-01"]),
                "value": values,
            }
        )
    if columns is not None:
        data = pd.DataFrame(columns)
    return SimpleNamespace(
        station_id=station_id,
        variable=variable,
        data=data,
        location=SimpleNamespace(x=1.0, y=2.0, crs="EPSG:2154", metadata={}),
        date_start=None,
        date_end=None,
    )


def _panels_cfg(**overrides):
    values = {
        "map_dem": False,
        "map_geology": False,
        "map_hydrography": False,
        "timeseries_discharge": False,
        "timeseries_piezometry": False,
        "timeseries_intermittency": False,
        "timeseries_water_quality": False,
        "climatic_summary": False,
        "stats_card": False,
        "station_inventory": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_wq_series_by_parameter_groups_sorts_and_ignores_invalid_records() -> None:
    grouped = report._wq_series_by_parameter(
        [
            _point_record(
                "S1",
                variable="NO3",
                values=[2.0, 1.0],
                dates=["2020-01-02", "2020-01-01"],
            ),
            _point_record("S2", variable="NO3", values=[3.0], dates=["2020-01-03"]),
            _point_record("S1", variable="CL", values=[10.0], dates=["2020-01-04"]),
            _point_record(
                "bad",
                variable="NO3",
                columns={"datetime": pd.to_datetime(["2020-01-01"]), "raw": [99.0]},
            ),
        ]
    )

    assert set(grouped) == {"NO3", "CL"}
    assert grouped["NO3"]["S1"].index.tolist() == list(pd.to_datetime(["2020-01-01", "2020-01-02"]))
    assert grouped["NO3"]["S1"].tolist() == [1.0, 2.0]
    assert grouped["NO3"]["S2"].tolist() == [3.0]
    assert grouped["CL"]["S1"].tolist() == [10.0]


def test_monthly_mean_from_points_averages_stations_and_leaves_missing_months_nan() -> None:
    monthly = report._monthly_mean_from_points(
        [
            _point_record(
                "P1",
                values=[1.0, 3.0, 10.0],
                dates=["2020-01-01", "2020-01-20", "2020-02-01"],
            ),
            _point_record(
                "P2",
                values=[5.0, 9.0],
                dates=["2020-01-10", "2020-03-01"],
            ),
        ]
    )

    assert monthly is not None
    assert monthly.shape == (12,)
    assert monthly[0] == pytest.approx(3.5)
    assert monthly[1] == pytest.approx(10.0)
    assert monthly[2] == pytest.approx(9.0)
    assert np.isnan(monthly[3])


def test_render_water_quality_draws_one_strip_per_parameter(mpl) -> None:
    fig, ax = mpl.subplots()
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

    try:
        assert len(axes) == 2
        assert axes[0].get_ylabel() == "NO3 (mg(NO3)/L)"
        assert axes[1].get_ylabel() == "CL"
        assert [line.get_label() for line in axes[1].lines] == ["S1", "S2 La riviere"]
        assert axes[0].lines[0].get_color() == axes[1].lines[0].get_color()
        assert axes[1].lines[1].get_ydata().tolist() == [6.0, 7.0]
        assert axes[0].get_legend() is not None
        assert axes[0].get_xlim()[0] <= axes[0].convert_xunits(pd.Timestamp("2019-12-31"))
    finally:
        mpl.close(fig)


@pytest.mark.fast
def test_water_quality_does_not_join_analyses_across_a_sampling_gap() -> None:
    serie = pd.Series(
        [1.0, 2.0, 3.0], index=pd.to_datetime(["2020-01-01", "2020-02-01", "2021-01-01"])
    )

    broken = panels._break_gaps(serie, 120)

    assert broken.isna().sum() == 1
    assert broken.dropna().tolist() == [1.0, 2.0, 3.0]
    assert broken.index.is_monotonic_increasing


def test_render_climatic_summary_places_monthly_precip_and_etp_bars(mpl) -> None:
    fig, ax = mpl.subplots()

    panels.render_climatic_summary(
        ax,
        monthly_precip=np.arange(1, 13, dtype=float),
        monthly_etp=np.full(12, 2.5),
        title="Monthly climate",
    )

    try:
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
    finally:
        mpl.close(fig)


def test_render_intermittency_draws_one_flow_state_strip_per_station(mpl) -> None:
    fig, ax = mpl.subplots()
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

    try:
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
    finally:
        mpl.close(fig)


def test_render_station_inventory_empty_state_is_explicit(mpl) -> None:
    fig, ax = mpl.subplots()

    panels.render_station_inventory(ax, inventory=[])

    try:
        assert ax.texts[0].get_text() == "No stations loaded"
        assert not ax.axison
    finally:
        mpl.close(fig)


def test_monthly_mean_from_fields_averages_space_and_multiple_records() -> None:
    xr = pytest.importorskip("xarray")
    time = pd.to_datetime(["2020-01-01", "2020-01-15", "2020-02-01"])
    first = xr.Dataset(
        {
            "precipitation": (
                ("time", "y", "x"),
                np.asarray(
                    [
                        [[1.0, 3.0], [5.0, 7.0]],
                        [[2.0, 4.0], [6.0, 8.0]],
                        [[10.0, 14.0], [18.0, 22.0]],
                    ]
                ),
            )
        },
        coords={"time": time},
    )
    second = xr.Dataset({"value": ("time", [6.0])}, coords={"time": [pd.Timestamp("2020-01-01")]})

    monthly = report._monthly_mean_from_fields(
        [SimpleNamespace(dataset=first), SimpleNamespace(dataset=second)]
    )

    assert monthly is not None
    assert monthly[0] == pytest.approx(5.25)
    assert monthly[1] == pytest.approx(16.0)
    assert np.isnan(monthly[2])


def test_build_station_points_groups_available_locations() -> None:
    loaded_data = SimpleNamespace(
        hydrometry=SimpleNamespace(
            points=[_point_record("H1", variable="discharge", values=[1.0])]
        ),
        piezometry=SimpleNamespace(points=[_point_record("P1", variable="head", values=[2.0])]),
        intermittency=SimpleNamespace(points=[_point_record("O1", variable="state", values=[5.0])]),
        water_quality=SimpleNamespace(points=[_point_record("W1", variable="NO3", values=[3.0])]),
    )

    points = report._build_station_points(loaded_data)

    assert points is not None
    assert [(point["label"], point["marker"], point["group"]) for point in points] == [
        ("H1", "o", "Hydrometry"),
        ("P1", "^", "Piezometry"),
        ("O1", "s", "Intermittency"),
        ("W1", "D", "Water quality"),
    ]


def test_map_panels_render_minimal_raster_without_optional_vectors(tmp_path, mpl) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    dem = tmp_path / "dem.tif"
    with rasterio.open(
        dem,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        transform=from_origin(100.0, 200.0, 10.0, 10.0),
    ) as dst:
        dst.write(np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype="float32"), 1)

    fig, axes = mpl.subplots(1, 3)
    panels.render_dem_map(
        axes[0],
        dem_path=str(dem),
        station_points=[
            {
                "x": 105.0,
                "y": 195.0,
                "crs": None,
                "label": "H1",
                "marker": "o",
                "color": "white",
                "group": "Hydrometry",
            },
            {
                "x": 5100.0,
                "y": 5190.0,
                "crs": None,
                "label": "P1",
                "marker": "^",
                "color": "skyblue",
                "group": "Piezometry",
            },
        ],
        title="DEM",
    )
    panels.render_hydrography_map(
        axes[1],
        dem_path=str(dem),
        outlet_xy=(105.0, 195.0),
        title="Hydro",
    )
    panels.render_geology_map(axes[2], dem_path=str(dem), title="Geo")

    try:
        assert axes[0].get_title() == "DEM"
        legend = axes[0].get_legend()
        assert [text.get_text() for text in legend.get_texts()] == [
            "Hydrometry",
            "Piezometry (off map, 7 km NE)",
        ]
        assert axes[1].lines[0].get_marker() == "*"
        assert axes[2].get_title() == "Geo"
        assert all(axis.get_aspect() == 1.0 for axis in axes)
    finally:
        mpl.close(fig)


def test_regional_context_map_draws_the_stations_it_covers(tmp_path, mpl) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    dem = tmp_path / "regional.tif"
    with rasterio.open(
        dem,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        transform=from_origin(0.0, 20000.0, 10000.0, 10000.0),
    ) as dst:
        dst.write(np.ones((1, 2, 2), dtype="float32"))

    fig, ax = mpl.subplots()
    panels.render_regional_context_map(
        ax,
        regional_dem_path=str(dem),
        station_points=[
            {"x": 15000.0, "y": 18000.0, "crs": None, "marker": "^", "group": "Piezometry"}
        ],
        title="Regional",
    )

    try:
        assert ax.collections[-1].get_offsets().tolist() == [[15000.0, 18000.0]]
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert labels == ["Catchment", "Piezometry"]
    finally:
        mpl.close(fig)


def test_generate_overview_report_writes_enabled_panel_pngs(tmp_path, mpl) -> None:
    loaded_data = SimpleNamespace(
        hydrometry=SimpleNamespace(
            points=[
                _point_record(
                    "H1",
                    variable="discharge",
                    values=[2.0, 3.0],
                    dates=["2020-01-01", "2020-01-02"],
                )
            ]
        ),
        piezometry=None,
        intermittency=None,
        water_quality=None,
        hydrography=None,
        geology=None,
        precipitation=None,
        etp=None,
    )
    state = SimpleNamespace(
        cfg=SimpleNamespace(
            overview=SimpleNamespace(
                name="Naizin",
                date_start="2020-01-01",
                date_end="2020-01-31",
                panels=_panels_cfg(timeseries_discharge=True, stats_card=True),
            )
        ),
        loaded_data=loaded_data,
        domain_geographic=SimpleNamespace(
            watershed_box_buff_dem=None,
            watershed_shp=None,
            catchment_area_km2=12.5,
            x_outlet=1.0,
            y_outlet=2.0,
        ),
        workspace=SimpleNamespace(project_root=tmp_path),
    )

    paths = report.generate_overview_report(state, [])

    assert [path.name for path in paths] == ["timeseries_discharge.png", "stats_card.png"]
    assert all(path.parent == tmp_path / "runs" / "Naizin" / "figures" for path in paths)
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)


# An overview is a run: claimed, pulsed, written in its directory, sealed completed.
#
# The overview claims ``runs/<site>/`` through the attempt protocol: its outcome
# is written before anything else, its panels and pages land in the run
# directory, the seal holds a record without solver tables (``manifest.json``
# last, ``README.md``), the outcome flips to ``completed`` and ``.hmp/`` of the
# run is gone. A second overview of the same site takes ``.v2``; an overview
# that fails leaves a failed outcome and no manifest.

_TOML = """\
[site]
name = "nancon"

[workflow]
mode = "overview"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[overview]
name = "identity card"
date_start = "2010-01-01"
date_end = "2012-12-31"
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    (root / "project.toml").write_text("", encoding="utf-8")
    (root / "dem.tif").write_bytes(b"never read: the phases are replaced")
    (root / "overview.toml").write_text(_TOML, encoding="utf-8")
    launcher = overview_module.DataOverviewLauncher
    for phase in (
        "_setup_geographic",
        "_load_data",
    ):
        monkeypatch.setattr(launcher, phase, lambda *args, **kwargs: None)
    monkeypatch.setattr(
        launcher, "_resolve_geographic_inputs", lambda self, state: (None, root / "dem.tif")
    )
    monkeypatch.setattr(launcher, "_write_page", staticmethod(_write_index))
    return root


def _write_index(run_dir: Path) -> Path:
    index = run_dir / "report" / "index.html"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("<html></html>", encoding="utf-8")
    return index


def _draw_one_panel(monkeypatch: pytest.MonkeyPatch, seen: dict) -> None:
    def generate(state, inventory) -> list[Path]:
        seen["inventory"] = inventory
        run_dir = overview_run_dir_of(state)
        seen["outcome"] = read_outcome(run_dir)
        figures = overview_figures_dir(run_dir)
        figures.mkdir(parents=True, exist_ok=True)
        panel = figures / "location.png"
        panel.write_bytes(b"png")
        return [panel]

    monkeypatch.setattr(
        overview_module.DataOverviewLauncher, "_generate_report", staticmethod(generate)
    )


def test_an_overview_claims_writes_and_seals_its_run_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}
    _draw_one_panel(monkeypatch, seen)

    summary = run_overview(request_of(project / "overview.toml"), base=project).to_dict()

    run_dir = project / "runs" / "nancon"
    assert summary["run_dir"] == str(run_dir)
    assert summary["name"] == "nancon"
    assert summary["web_report"] == str(run_dir / "report" / "index.html")
    assert seen["inventory"] == []
    assert seen["outcome"] is not None and seen["outcome"].status == "running"
    assert (run_dir / "figures" / "location.png").is_file()
    assert effective_status(run_dir) == "completed"
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "completed"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run"]["solver"] == "overview"
    assert manifest["site"]["name"] == "nancon"
    assert manifest["config"]["file"] == "config.toml"
    assert (run_dir / "README.md").is_file()
    assert (run_dir / "config.toml").is_file()
    assert not (run_dir / ".hmp").exists()
    assert not (run_dir / "fields.zarr").exists()


def test_the_seal_holds_the_inventory_and_lists_the_loaded_inputs(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.results.record.manifest import InputEntry

    _draw_one_panel(monkeypatch, {})
    row = {
        "row_kind": "family",
        "family": "recharge",
        "source": "synthetic",
        "item_id": "",
        "name": None,
        "x": None,
        "y": None,
        "crs_epsg": None,
        "first": None,
        "last": None,
        "records": 2,
        "mean_value": 365.25,
        "unit": "mm/year",
    }
    entry = InputEntry(variable="recharge:recharge", provider="synthetic", path="data/r.csv")
    monkeypatch.setattr(overview_module, "inventory_rows", lambda state: [row])
    monkeypatch.setattr(overview_module, "loaded_inputs", lambda state, root: [entry])

    run_overview(request_of(project / "overview.toml"), base=project)

    run_dir = project / "runs" / "nancon"
    table = pd.read_parquet(run_dir / "tables.parquet" / "data_inventory.parquet")
    assert table[["family", "records", "unit"]].to_dict("records") == [
        {"family": "recharge", "records": 2, "unit": "mm/year"}
    ]
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    assert [item["variable"] for item in inputs["inputs"]] == ["recharge:recharge"]


def test_a_second_overview_of_the_same_site_takes_the_next_version(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _draw_one_panel(monkeypatch, {})
    run_overview(request_of(project / "overview.toml"), base=project)

    second = run_overview(request_of(project / "overview.toml"), base=project).to_dict()

    assert second["run_dir"] == str(project / "runs" / "nancon.v2")
    assert overview_run_dir(project, "nancon") == project / "runs" / "nancon.v2"
    assert (project / "runs" / "nancon.v2" / "figures" / "location.png").is_file()


def test_a_failed_overview_leaves_a_failed_outcome_and_no_manifest(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(state, inventory) -> list[Path]:
        raise RuntimeError("no panel today")

    monkeypatch.setattr(
        overview_module.DataOverviewLauncher, "_generate_report", staticmethod(broken)
    )

    with pytest.raises(RuntimeError, match="no panel today"):
        run_overview(request_of(project / "overview.toml"), base=project)

    run_dir = project / "runs" / "nancon"
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "failed"
    assert outcome.error is not None and outcome.error.message == "no panel today"
    assert not (run_dir / "manifest.json").exists()
