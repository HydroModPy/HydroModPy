"""Tests for display.adapters — PointRecord → display format helpers."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.analysis.display.adapters import (
    observed_discharge_series,
    observed_piezometry_series,
)


def _make_record(
    station_id: str = "ST001",
    variable: str = "discharge",
    values: list[float] | None = None,
    start: str = "2020-01-01",
    n_days: int = 90,
    unit: str = "m3/s",
    loc_x: float = -1.5,
    loc_y: float = 48.0,
) -> PointRecord:
    dates = pd.date_range(start, periods=n_days, freq="D")
    if values is None:
        values = [1.0] * n_days
    df = pd.DataFrame({"datetime": dates, "value": values[:n_days]})
    return PointRecord(
        station_id=station_id,
        variable=variable,
        source="test",
        unit=unit,
        frequency="D",
        data=df,
        date_start=datetime.fromisoformat(start),
        date_end=dates[-1].to_pydatetime(),
        location=StationLocation(id=station_id, x=loc_x, y=loc_y, crs="EPSG:4326"),
    )


# ---------------------------------------------------------------------------
# observed_discharge_series
# ---------------------------------------------------------------------------

class TestObservedDischargeSeries:

    def test_returns_none_for_empty_list(self):
        assert observed_discharge_series([]) is None

    def test_returns_dataframe_with_Q_column(self):
        r = _make_record(variable="discharge")
        result = observed_discharge_series([r], freq=None)
        assert result is not None
        assert "Q" in result.columns
        assert len(result) == 90

    def test_resamples_to_monthly(self):
        r = _make_record(variable="discharge", n_days=365)
        result = observed_discharge_series([r], freq="ME")
        assert result is not None
        assert len(result) == 12  # one row per month

    def test_selects_by_station_id(self):
        r1 = _make_record(station_id="A", variable="discharge", values=[1.0] * 90)
        r2 = _make_record(station_id="B", variable="discharge", values=[5.0] * 90)
        result = observed_discharge_series([r1, r2], station_id="B", freq=None)
        assert result is not None
        assert result["Q"].iloc[0] == pytest.approx(5.0)

    def test_returns_none_when_station_not_found(self):
        r = _make_record(station_id="A")
        assert observed_discharge_series([r], station_id="MISSING") is None

    def test_normalises_by_area(self):
        # 1 m³/s over 1 km² = 1e6 m²
        # → 1 * 86400 * 1000 / 1e6 = 86.4 mm/day
        r = _make_record(variable="discharge", values=[1.0] * 30, n_days=30)
        result = observed_discharge_series([r], freq=None, area_m2=1_000_000)
        assert result is not None
        assert result["Q"].iloc[0] == pytest.approx(86.4)

    def test_prefers_discharge_variable(self):
        r1 = _make_record(station_id="A", variable="water_level", values=[99.0] * 90)
        r2 = _make_record(station_id="B", variable="discharge", values=[2.0] * 90)
        result = observed_discharge_series([r1, r2], freq=None)
        assert result is not None
        assert result["Q"].iloc[0] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# observed_piezometry_series
# ---------------------------------------------------------------------------

class TestObservedPiezometrySeries:

    def test_returns_none_for_empty_list(self):
        assert observed_piezometry_series([]) is None

    def test_returns_dataframe_with_station_columns(self):
        r1 = _make_record(station_id="BSS001", variable="groundwater_level", values=[10.0] * 30, n_days=30)
        r2 = _make_record(station_id="BSS002", variable="groundwater_level", values=[20.0] * 30, n_days=30)
        result = observed_piezometry_series([r1, r2])
        assert result is not None
        assert "BSS001" in result.columns
        assert "BSS002" in result.columns
        assert result["BSS001"].iloc[0] == pytest.approx(10.0)
        assert result["BSS002"].iloc[0] == pytest.approx(20.0)

    def test_resamples_when_freq_given(self):
        r = _make_record(station_id="BSS001", variable="groundwater_level", n_days=365)
        result = observed_piezometry_series([r], freq="ME")
        assert result is not None
        assert len(result) == 12

    def test_single_record(self):
        r = _make_record(station_id="BSS001", variable="groundwater_level", n_days=10)
        result = observed_piezometry_series([r])
        assert result is not None
        assert len(result) == 10
        assert list(result.columns) == ["BSS001"]
