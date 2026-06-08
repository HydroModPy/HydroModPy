"""Explicit unit conversions for LAK forcings and leakance.

MF6 LAK keeps two unit conventions that must never be confused: ``rainfall`` /
``evaporation`` are rates (L/T) while ``runoff`` / ``inflow`` / ``withdrawal``
and the SPECIFIED outlet ``rate`` are volumetric (L^3/T). The lake-bed leakance
``bedleak`` is an inverse time (1/T). HMP runs MF6 in seconds, so all of these
must reach the solver in canonical SI (m/s, m3/s, 1/s). These tests pin the exact
converted numbers so a silent rate/volumetric mix-up cannot pass.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.units.hydraulic_conductivity import parse_to_m_per_s
from hydromodpy.core.units.leakance import (
    convert_to_per_s,
    factor_to_per_s,
    normalize_per_s_unit,
    parse_to_per_s,
)
from hydromodpy.core.units.volumetric_flow import parse_to_m3_per_s
from hydromodpy.solver.modflow6.builders.lake import (
    build_lake_period_data,
    convert_bedleak_to_per_s,
)


def test_inflow_volumetric_round_trip_matches_legacy_days_value() -> None:
    # Legacy days+metres example: an inflow of 0.5 m3/s is
    # 43200 m3/day. The conversion layer must map both spellings to the same
    # canonical SI value (0.5 m3/s) for HMP's seconds-based TDIS.
    from_seconds, _ = parse_to_m3_per_s(0.5, location="lake.inflow", default_unit="m3/s")
    from_days, _ = parse_to_m3_per_s(43200.0, location="lake.inflow", default_unit="m3/day")
    assert from_seconds == pytest.approx(0.5)
    assert from_days == pytest.approx(0.5)
    # The factor that produced 43200 from 0.5 is exactly the seconds-per-day count.
    assert 43200.0 / 0.5 == pytest.approx(86400.0)


def test_rainfall_rate_converts_mm_per_day_to_m_per_s() -> None:
    # 4 mm/day rainfall rate -> 4e-3 m / 86400 s.
    value_si, canonical = parse_to_m_per_s(4.0, location="lake.rainfall", default_unit="mm/day")
    assert value_si == pytest.approx(4.0e-3 / 86400.0)
    assert canonical == "mm/day"


def test_leakance_one_per_day_converts_to_one_per_second() -> None:
    assert normalize_per_s_unit("1/d") == "1/day"
    assert factor_to_per_s("1/day") == pytest.approx(1.0 / 86400.0)
    assert convert_to_per_s(1.0, unit="1/day") == pytest.approx(1.0 / 86400.0)
    value_si, canonical = parse_to_per_s(1.0, location="lake.bedleak", explicit_unit="1/day")
    assert value_si == pytest.approx(1.0 / 86400.0)
    assert canonical == "1/day"
    assert convert_bedleak_to_per_s(1.0, lake_id="lac0", unit="1/day") == pytest.approx(
        1.0 / 86400.0
    )


def test_leakance_rejects_an_incompatible_unit() -> None:
    # A length unit is not a leakance (1/T); the typo must not silently pass.
    with pytest.raises(ValueError, match="leakance"):
        parse_to_per_s(1.0, location="lake.bedleak", explicit_unit="m")


def test_build_lake_period_data_separates_rate_and_volumetric_keywords() -> None:
    # rainfall/evaporation are rates (m/s); runoff/inflow/withdrawal volumetric
    # (m3/s). The builder must convert each with the right convention.
    lakes = {
        "lac0": {
            "rainfall": {"value": 4.0, "units": "mm/day"},
            "evaporation": {"value": 2.0, "units": "mm/day"},
            "inflow": {"value": 43200.0, "units": "m3/day"},
            "runoff": {"value": 1.0e4, "units": "m3/day"},
            "withdrawal": {"value": 0.5, "units": "m3/s"},
        }
    }
    rows, ts_specs = build_lake_period_data(None, lakes=lakes)
    by_keyword = {row[1]: row[2] for row in rows}

    assert ts_specs == []
    assert by_keyword["rainfall"] == pytest.approx(4.0e-3 / 86400.0)
    assert by_keyword["evaporation"] == pytest.approx(2.0e-3 / 86400.0)
    assert by_keyword["inflow"] == pytest.approx(0.5)
    assert by_keyword["runoff"] == pytest.approx(1.0e4 / 86400.0)
    assert by_keyword["withdrawal"] == pytest.approx(0.5)
    # Every row carries the 0-based lake index as its first element.
    assert all(row[0] == 0 for row in rows)


def test_build_lake_period_data_skips_non_constant_forcings() -> None:
    # A CSV / TS6 forcing is resolved at runtime, not in the static perioddata.
    lakes = {
        "lac0": {
            "inflow": {"kind": "csv", "path_file": "series.csv"},
            "rainfall": {"kind": "constant", "value": 0.001, "units": "m/day"},
        }
    }
    rows, ts_specs = build_lake_period_data(None, lakes=lakes)
    keywords = {row[1] for row in rows}
    assert keywords == {"rainfall"}
    assert ts_specs == []
    assert rows[0][2] == pytest.approx(0.001 / 86400.0)
