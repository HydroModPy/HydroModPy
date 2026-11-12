"""Data behind the overview report: time series per station, monthly means (mm) and map points.

A record is one station of one variable, with its table of dates and values. The report
writes one PNG per enabled panel in ``runs/<site>/figures/``.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.overview import report
from hydromodpy.display.overview.report import _piezo_altitude_hlines, _records_to_timeseries_df


def record(
    station_id: str,
    *,
    variable: str | None = "discharge",
    values: list[float] | None = None,
    dates: list[str] | None = None,
    columns: dict[str, object] | None = None,
    altitude: object = None,
):
    """A station record. ``columns`` replaces the table with columns of your own."""
    data = None
    if values is not None:
        data = pd.DataFrame({"datetime": pd.to_datetime(dates), "value": values})
    if columns is not None:
        data = pd.DataFrame(columns)
    metadata = {} if altitude is None else {"altitude": altitude}
    return SimpleNamespace(
        station_id=station_id,
        variable=variable,
        data=data,
        location=SimpleNamespace(x=1.0, y=2.0, crs="EPSG:2154", metadata=metadata),
        date_start=None,
        date_end=None,
    )


def no_panel() -> dict[str, bool]:
    return {
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


def test_timeseries_frame_of_records() -> None:
    frame = _records_to_timeseries_df(
        [
            record("H1", values=[2.0, 1.0], dates=["2020-01-02", "2020-01-01"]),
            record("H2", values=[4.0, 3.0], dates=["2020-01-03", "2020-01-01"]),
            record("empty"),
        ]
    )

    assert list(frame.index) == list(pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]))
    assert frame["H1"].tolist() == [1.0, 2.0, pytest.approx(float("nan"), nan_ok=True)]
    assert frame.loc[pd.Timestamp("2020-01-03"), "H2"] == 4.0
    assert _records_to_timeseries_df([]) is None


def test_piezometer_ground_lines() -> None:
    # Only a numeric altitude gives a line.
    hlines = _piezo_altitude_hlines(
        [
            record("P1", altitude="42.5"),
            record("P2", altitude="bad"),
            SimpleNamespace(station_id="P3", location=None),
        ]
    )

    assert hlines == [
        {"y": 42.5, "label": "P1 ground (42.5 m)", "color": "darkred", "linestyle": "--"}
    ]


def test_water_quality_series_by_parameter() -> None:
    grouped = report._wq_series_by_parameter(
        [
            record("S1", variable="NO3", values=[2.0, 1.0], dates=["2020-01-02", "2020-01-01"]),
            record("S2", variable="NO3", values=[3.0], dates=["2020-01-03"]),
            record("S1", variable="CL", values=[10.0], dates=["2020-01-04"]),
            # No "value" column: the record is ignored.
            record(
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


def test_monthly_mean_of_stations() -> None:
    monthly = report._monthly_mean_from_points(
        [
            record("P1", values=[1.0, 3.0, 10.0], dates=["2020-01-01", "2020-01-20", "2020-02-01"]),
            record("P2", values=[5.0, 9.0], dates=["2020-01-10", "2020-03-01"]),
        ]
    )

    assert monthly.shape == (12,)
    assert monthly[0] == pytest.approx(3.5)  # P1 gives 2, P2 gives 5, then the two stations average
    assert monthly[1] == pytest.approx(10.0)
    assert monthly[2] == pytest.approx(9.0)
    assert np.isnan(monthly[3])


def test_monthly_mean_of_fields() -> None:
    xr = pytest.importorskip("xarray")
    time = pd.to_datetime(["2020-01-01", "2020-01-15", "2020-02-01"])
    # Precipitation (mm) on a 2 x 2 grid: January means 4 and 5, February 16.
    grid = np.asarray(
        [
            [[1.0, 3.0], [5.0, 7.0]],
            [[2.0, 4.0], [6.0, 8.0]],
            [[10.0, 14.0], [18.0, 22.0]],
        ]
    )
    first = xr.Dataset({"precipitation": (("time", "y", "x"), grid)}, coords={"time": time})
    second = xr.Dataset({"value": ("time", [6.0])}, coords={"time": [pd.Timestamp("2020-01-01")]})

    monthly = report._monthly_mean_from_fields(
        [SimpleNamespace(dataset=first), SimpleNamespace(dataset=second)]
    )

    assert monthly[0] == pytest.approx(5.25)  # mean of 4, 5 and 6
    assert monthly[1] == pytest.approx(16.0)
    assert np.isnan(monthly[2])


def test_station_points_by_group() -> None:
    loaded_data = SimpleNamespace(
        hydrometry=SimpleNamespace(points=[record("H1", values=[1.0], dates=["2020-01-01"])]),
        piezometry=SimpleNamespace(
            points=[record("P1", variable="head", values=[2.0], dates=["2020-01-01"])]
        ),
        intermittency=SimpleNamespace(
            points=[record("O1", variable="state", values=[5.0], dates=["2020-01-01"])]
        ),
        water_quality=SimpleNamespace(
            points=[record("W1", variable="NO3", values=[3.0], dates=["2020-01-01"])]
        ),
    )

    points = report._build_station_points(loaded_data)

    assert [(point["label"], point["marker"], point["group"]) for point in points] == [
        ("H1", "o", "Hydrometry"),
        ("P1", "^", "Piezometry"),
        ("O1", "s", "Intermittency"),
        ("W1", "D", "Water quality"),
    ]


def test_report_writes_enabled_panels(tmp_path, mpl) -> None:
    loaded_data = SimpleNamespace(
        hydrometry=SimpleNamespace(
            points=[record("H1", values=[2.0, 3.0], dates=["2020-01-01", "2020-01-02"])]
        ),
        piezometry=None,
        intermittency=None,
        water_quality=None,
        hydrography=None,
        geology=None,
        precipitation=None,
        etp=None,
    )
    panels = SimpleNamespace(**(no_panel() | {"timeseries_discharge": True, "stats_card": True}))
    state = SimpleNamespace(
        cfg=SimpleNamespace(
            overview=SimpleNamespace(
                name="Naizin", date_start="2020-01-01", date_end="2020-01-31", panels=panels
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
