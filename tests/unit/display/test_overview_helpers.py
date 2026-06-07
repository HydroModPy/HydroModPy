"""Unit tests for overview data transformations and panels."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.display.overview.panels import render_timeseries_multi
from hydromodpy.display.overview.report import (
    _build_station_inventory,
    _piezo_altitude_hlines,
    _records_to_timeseries_df,
)
from hydromodpy.display.overview.summary import compute_overview_summary


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


def test_build_station_inventory_deduplicates_water_quality_periods() -> None:
    loaded = SimpleNamespace(
        hydrometry=SimpleNamespace(
            points=[
                _record("H1", date_start="2020-01-02", date_end="2020-01-03"),
            ]
        ),
        piezometry=None,
        intermittency=None,
        water_quality=SimpleNamespace(
            points=[
                _record("WQ1", variable="nitrate", date_start="2020-02-01", date_end="2020-02-10"),
                _record("WQ1", variable="chloride", date_start="2020-01-01", date_end="2020-03-01"),
            ]
        ),
    )
    state = SimpleNamespace(loaded_data=loaded)

    inventory = _build_station_inventory(state)

    assert inventory == [
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
    ]


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

    summary = compute_overview_summary(state)

    assert summary.watershed_name == "Naizin"
    assert summary.catchment_area_km2 == 12.5
    assert summary.outlet_xy == (1.25, 2.5)
    assert summary.n_hydrometry == 2
    assert summary.n_piezometry == 1
    assert summary.n_water_quality == 2
    assert summary.n_streams == 0
    assert summary.date_start == "2020-01-01"
