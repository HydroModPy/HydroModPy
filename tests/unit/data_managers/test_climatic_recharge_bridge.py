"""Tests for the forcing bridge (LoadResult -> flow-ready series)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord

from ._test_climatic_managers_builders import _make_field_record, _make_point_record


@pytest.mark.fast
class TestRechargeBridge:
    """Tests for the forcing bridge (LoadResult → flow-ready series)."""

    def test_extract_single_station(self):
        from hydromodpy.physics.forcing.forcing_bridge import extract_homogeneous_series

        rec = _make_point_record("A", n=5)
        result = LoadResult(points=[rec])
        series = extract_homogeneous_series(result)
        assert series is not None
        assert len(series) == 5
        assert series.iloc[0] == 0.0
        assert series.iloc[4] == 4.0

    def test_extract_multiple_stations_averages(self):
        from hydromodpy.physics.forcing.forcing_bridge import extract_homogeneous_series

        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        rec1 = PointRecord(
            station_id="A",
            variable="recharge",
            source="custom",
            unit="mm/d",
            frequency="D",
            data=pd.DataFrame({"datetime": dates, "value": [10.0, 20.0, 30.0]}),
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 3),
        )
        rec2 = PointRecord(
            station_id="B",
            variable="recharge",
            source="custom",
            unit="mm/d",
            frequency="D",
            data=pd.DataFrame({"datetime": dates, "value": [20.0, 40.0, 60.0]}),
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 3),
        )
        result = LoadResult(points=[rec1, rec2])
        series = extract_homogeneous_series(result)
        assert series is not None
        assert len(series) == 3
        assert series.iloc[0] == pytest.approx(15.0)
        assert series.iloc[1] == pytest.approx(30.0)

    def test_extract_no_points_returns_none(self):
        from hydromodpy.physics.forcing.forcing_bridge import extract_homogeneous_series

        result = LoadResult(fields=[_make_field_record()])
        assert extract_homogeneous_series(result) is None

    def test_extract_empty_result_returns_none(self):
        from hydromodpy.physics.forcing.forcing_bridge import extract_homogeneous_series

        result = LoadResult()
        assert extract_homogeneous_series(result) is None

    def test_build_forcing_series_converts_units(self):
        from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
        from hydromodpy.physics.forcing.forcing_bridge import build_forcing_series

        mm_day_to_m_s = factor_to_m_per_s("mm/day")
        rec = _make_point_record("A", n=3)
        result = LoadResult(points=[rec])
        series = build_forcing_series(
            result,
            unit_conversion_factor=mm_day_to_m_s,
            label="recharge",
        )
        assert series is not None
        # Value 1 (mm/day) → 1 * factor_to_m_per_s("mm/day") (m/s)
        assert series.iloc[1] == pytest.approx(1.0 * mm_day_to_m_s)

    def test_build_forcing_series_no_points_returns_none(self):
        from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
        from hydromodpy.physics.forcing.forcing_bridge import build_forcing_series

        result = LoadResult(fields=[_make_field_record()])
        assert (
            build_forcing_series(
                result,
                unit_conversion_factor=factor_to_m_per_s("mm/day"),
                label="recharge",
            )
            is None
        )

    def test_build_forcing_series_runoff_converts_units(self):
        from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
        from hydromodpy.physics.forcing.forcing_bridge import build_forcing_series

        mm_day_to_m_s = factor_to_m_per_s("mm/day")
        rec = _make_point_record("A", n=3)
        result = LoadResult(points=[rec])
        series = build_forcing_series(
            result,
            unit_conversion_factor=mm_day_to_m_s,
            label="runoff",
        )
        assert series is not None
        assert series.iloc[2] == pytest.approx(2.0 * mm_day_to_m_s)
