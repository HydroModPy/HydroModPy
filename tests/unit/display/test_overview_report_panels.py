"""Behavioral tests for overview report conversions and panels."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.overview import panels, report


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _record(
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
            _record(
                "S1",
                variable="NO3",
                values=[2.0, 1.0],
                dates=["2020-01-02", "2020-01-01"],
            ),
            _record("S2", variable="NO3", values=[3.0], dates=["2020-01-03"]),
            _record("S1", variable="CL", values=[10.0], dates=["2020-01-04"]),
            _record(
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
            _record(
                "P1",
                values=[1.0, 3.0, 10.0],
                dates=["2020-01-01", "2020-01-20", "2020-02-01"],
            ),
            _record(
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


def test_render_water_quality_transfers_grouped_series_to_lines(mpl) -> None:
    fig, ax = mpl.subplots()
    index = pd.to_datetime(["2020-01-01", "2020-01-02"])
    series_by_param = {
        "NO3": {"S1": pd.Series([1.0, 2.0], index=index)},
        "CL": {"S2": pd.Series([4.0, 5.0], index=index)},
    }

    panels.render_water_quality(
        ax,
        series_by_param=series_by_param,
        title="Water quality",
        date_start="2019-12-31",
        date_end="2020-01-03",
    )

    try:
        assert [line.get_label() for line in ax.lines] == ["NO3 (S1)", "CL (S2)"]
        assert ax.lines[0].get_ydata().tolist() == [1.0, 2.0]
        assert ax.lines[1].get_ydata().tolist() == [4.0, 5.0]
        assert ax.get_legend() is not None
        assert ax.get_xlim()[0] <= ax.convert_xunits(pd.Timestamp("2019-12-31"))
        assert ax.get_xlim()[1] >= ax.convert_xunits(pd.Timestamp("2020-01-03"))
    finally:
        mpl.close(fig)


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


def test_render_intermittency_uses_discrete_flow_state_axis(mpl) -> None:
    fig, ax = mpl.subplots()
    df = pd.DataFrame(
        {"O1": [1.0, 5.0], "O2": [np.nan, 3.0]},
        index=pd.to_datetime(["2020-01-01", "2020-02-01"]),
    )

    panels.render_intermittency(
        ax,
        df=df,
        title="ONDE",
        date_start="2020-01-01",
        date_end="2020-03-01",
    )

    try:
        assert len(ax.lines) == 2
        assert [tick.get_text() for tick in ax.get_yticklabels()] == [
            "1: Dry",
            "2: Non-visible",
            "3: Weak",
            "4: Acceptable",
            "5: Visible",
        ]
        assert ax.get_ylim() == pytest.approx((0.5, 5.5))
        assert ax.get_legend() is not None
    finally:
        mpl.close(fig)


def test_render_station_inventory_and_stats_card_render_expected_table_cells(mpl) -> None:
    fig, (ax_stats, ax_inventory) = mpl.subplots(1, 2)
    summary = SimpleNamespace(
        watershed_name="Naizin",
        catchment_area_km2=12.5,
        outlet_xy=(1.0, 2.0),
        date_start="2020-01-01",
        date_end="2020-12-31",
        n_streams=3,
        n_hydrometry=1,
        n_piezometry=2,
        n_intermittency=0,
        n_water_quality=4,
    )
    inventory = [
        {
            "type": "Hydrometry",
            "id": "H1",
            "x": 1.0,
            "y": 2.0,
            "start": "2020-01-01",
            "end": "2020-02-01",
        }
    ]

    panels.render_stats_card(ax_stats, summary=summary)
    panels.render_station_inventory(ax_inventory, inventory=inventory)

    try:
        stats_table = ax_stats.tables[0]
        inventory_table = ax_inventory.tables[0]
        assert stats_table[(0, 1)].get_text().get_text() == "Naizin"
        assert stats_table[(1, 1)].get_text().get_text() == "12.50 km²"
        assert inventory_table[(1, 1)].get_text().get_text() == "H1"
        assert "1 stations" in ax_inventory.get_title()
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
        hydrometry=SimpleNamespace(points=[_record("H1", variable="discharge", values=[1.0])]),
        piezometry=SimpleNamespace(points=[_record("P1", variable="head", values=[2.0])]),
        intermittency=SimpleNamespace(points=[_record("O1", variable="state", values=[5.0])]),
        water_quality=SimpleNamespace(points=[_record("W1", variable="NO3", values=[3.0])]),
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
            }
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
        assert axes[0].get_legend() is not None
        assert axes[1].lines[0].get_marker() == "*"
        assert axes[2].get_title() == "Geo"
        assert all(axis.get_aspect() == 1.0 for axis in axes)
    finally:
        mpl.close(fig)


def test_generate_overview_report_writes_enabled_panel_pngs(tmp_path, mpl) -> None:
    loaded_data = SimpleNamespace(
        hydrometry=SimpleNamespace(
            points=[
                _record(
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
        workspace=SimpleNamespace(paths=SimpleNamespace(figures_folder=tmp_path / "figures")),
    )

    paths = report.generate_overview_report(state)

    assert [path.name for path in paths] == ["timeseries_discharge.png", "stats_card.png"]
    assert all(path.parent == tmp_path / "figures" / "overview" for path in paths)
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)
