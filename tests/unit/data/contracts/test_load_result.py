"""Load result: the points, fields and tables a variable hands up, and the series built from them."""

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.core.units.quantities import factor_to_m_per_s
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.forcing.forcing_bridge import (
    build_forcing_series,
    extract_homogeneous_series,
)
from tests._helpers.data_climatic_builders import _make_field_record, _make_point_record


def test_an_empty_result_is_false():
    assert not LoadResult()


def test_an_empty_result_has_no_records():
    assert LoadResult().all_records == []


def test_points_count():
    assert len(LoadResult(points=[_make_point_record(), _make_point_record("ST02")])) == 2


def test_points_are_true():
    assert LoadResult(points=[_make_point_record()])


def test_fields_count():
    assert len(LoadResult(fields=[_make_field_record()])) == 1


def test_all_records_is_a_flat_list():
    point = _make_point_record()
    field = _make_field_record()

    flat = LoadResult(points=[point], fields=[field]).all_records

    assert len(flat) == 2
    assert flat[0] is point
    assert flat[1] is field


def test_warnings_are_kept():
    result = LoadResult(warnings=["Station S2 missing data", "Timeout on API"])

    assert len(result.warnings) == 2
    assert "Timeout" in result.warnings[1]


def test_warnings_are_not_shared():
    first = LoadResult()
    first.warnings.append("oops")

    assert LoadResult().warnings == []


def test_several_stations_average_into_one_series():
    dates = pd.date_range("2020-01-01", periods=3, freq="D")

    def recharge(station_id, values):
        return PointRecord(
            station_id=station_id,
            variable="recharge",
            source="file",
            unit="mm/d",
            frequency="D",
            data=pd.DataFrame({"datetime": dates, "value": values}),
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 3),
        )

    result = LoadResult(
        points=[recharge("A", [10.0, 20.0, 30.0]), recharge("B", [20.0, 40.0, 60.0])]
    )

    series = extract_homogeneous_series(result)

    assert len(series) == 3
    assert series.iloc[0] == pytest.approx(15.0)
    assert series.iloc[1] == pytest.approx(30.0)


@pytest.mark.parametrize(("label", "index"), [("recharge", 1), ("runoff", 2)])
def test_forcing_series_converts_units(label, index):
    # The record holds value = day index, in mm/day.
    mm_day_to_m_s = factor_to_m_per_s("mm/day")
    result = LoadResult(points=[_make_point_record("A", n=3)])

    series = build_forcing_series(result, unit_conversion_factor=mm_day_to_m_s, label=label)

    assert series.iloc[index] == pytest.approx(index * mm_day_to_m_s)
