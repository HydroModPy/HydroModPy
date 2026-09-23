"""A flux is averaged over its period, a state is read at its stamp.

A run stamps each stress period at its END. A discharge stands for the whole
period ``[start, stamp)``, so its observations are averaged there. A MODFLOW
head or a lake stage is the state AT the stamp instant: averaging over the
period that ends there compares it with a value half a period earlier, the
very bias the period rule removed for discharge. The field registry already
says which is which in its CF ``cell_methods``.

The chronicle below is worth its day number, counted from 2000-01-01 = 0, so
every window mean is the middle of the days it holds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.time_method import OBSERVABLE_TIME_METHODS
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    first_period_start,
    observed_on_simulation_index,
    time_method_for,
)
from hydromodpy.results.field_registry import FIELD_REGISTRY

DAYS_2000 = pd.date_range("2000-01-01", "2000-12-31", freq="D")
DAY_NUMBER = pd.Series(np.arange(len(DAYS_2000), dtype=float), index=DAYS_2000)
# January, February and March of a monthly run, stamped at their ends.
MONTH_ENDS = pd.DatetimeIndex(["2000-02-01", "2000-03-01", "2000-04-01"])


def test_a_monthly_head_on_a_daily_chronicle_takes_the_window_centred_on_its_stamp() -> None:
    # The stamp 2000-03-01 sits 29 days after 02-01 and 31 days before 04-01.
    # Its window reaches halfway to each: [02-15 12:00, 03-16 12:00), the days
    # 16 February to 16 March, day numbers 46 to 75, mean 60.5.
    aligned = observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="point")

    assert aligned.iloc[1] == pytest.approx((46 + 75) / 2)


def test_a_monthly_discharge_on_a_daily_chronicle_takes_the_month_its_stamp_closes() -> None:
    # The stamp 2000-03-01 closes February, [02-01, 03-01): day numbers 31 to
    # 59, mean 45. The head above read 60.5 on the same record: half a month
    # apart, which is what averaging a state over its period would cost.
    aligned = observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="mean")

    assert aligned.iloc[1] == pytest.approx((31 + 59) / 2)


def test_a_lake_stage_at_the_run_frequency_takes_the_reading_at_its_stamp() -> None:
    # Monthly readings taken on the first of each month, as a run stamps.
    readings = pd.Series(
        [1.0, 2.0, 3.0, 4.0, 5.0], index=pd.date_range("2000-01-01", periods=5, freq="MS")
    )

    stage = observed_on_simulation_index(readings, MONTH_ENDS, method=time_method_for("stage"))
    as_a_flux = observed_on_simulation_index(readings, MONTH_ENDS, method="mean")

    # The stage at 03-01 is the reading of 03-01. The period mean would hand it
    # the reading of 02-01, a month early.
    assert stage.tolist() == [2.0, 3.0, 4.0]
    assert as_a_flux.tolist() == [1.0, 2.0, 3.0]


def test_a_state_reads_the_nearest_sample_within_one_run_step_and_no_further() -> None:
    readings = pd.Series([10.0, 20.0], index=pd.DatetimeIndex(["2000-01-01", "2000-01-05"]))
    stamps = pd.date_range("2000-01-01", periods=3, freq="D")

    aligned = observed_on_simulation_index(readings, stamps, method="point")

    # 01-02 is one day from 01-01, within one run step; 01-03 is two days from
    # both readings, beyond it.
    assert aligned.iloc[:2].tolist() == [10.0, 10.0]
    assert np.isnan(aligned.iloc[2])


def test_a_tie_between_two_readings_goes_to_the_earlier_one() -> None:
    # A daily state stamped at midnight between two noon readings.
    readings = pd.Series(
        [1.0, 2.0], index=pd.DatetimeIndex(["2000-01-01 12:00", "2000-01-02 12:00"])
    )

    aligned = observed_on_simulation_index(
        readings, pd.DatetimeIndex(["2000-01-02", "2000-01-03"]), method="point"
    )

    assert aligned.tolist() == [1.0, 2.0]


def test_a_state_on_millisecond_parquet_stamps_is_read_without_a_merge() -> None:
    # The nearest-sample branch used pandas.merge_asof, which refused to join
    # millisecond stamps with nanosecond ones.
    readings = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2000-01-01", periods=3, freq="D"))
    simulated = pd.Series(
        [1.5, 2.5, 3.5], index=pd.date_range("2000-01-01", periods=3, freq="D").as_unit("ms")
    )

    paired = align_observed_simulated(readings, simulated, method="point")

    assert paired["obs"].tolist() == [1.0, 2.0, 3.0]


def test_one_steady_discharge_period_with_its_start_takes_its_own_window() -> None:
    index = pd.date_range("1999-01-01", "2001-12-31", freq="D")
    record = pd.Series(index.year.astype("float64"), index=index)

    aligned = observed_on_simulation_index(
        record, pd.DatetimeIndex(["2001-01-01"]), method="mean", start="2000-01-01"
    )

    assert aligned.tolist() == [2000.0]


def test_one_steady_discharge_period_without_a_start_takes_the_whole_chronicle() -> None:
    # 365 days of 1999, 366 of 2000, 365 of 2001. The last day before the stamp,
    # 2000.0, would be one day scored as a steady stage.
    index = pd.date_range("1999-01-01", "2001-12-31", freq="D")
    record = pd.Series(index.year.astype("float64"), index=index)

    aligned = observed_on_simulation_index(record, pd.DatetimeIndex(["2001-01-01"]), method="mean")

    assert aligned.tolist() == [pytest.approx((1999 * 365 + 2000 * 366 + 2001 * 365) / 1096)]


def test_the_start_of_a_series_is_the_grid_bound_just_before_its_first_stamp() -> None:
    bounds = pd.date_range("2000-01-01", periods=4, freq="MS")

    assert first_period_start(pd.DatetimeIndex(["2000-02-01"]), bounds) == bounds[0]
    assert first_period_start(pd.DatetimeIndex(["2000-04-01"]), bounds) == bounds[2]
    assert first_period_start(pd.DatetimeIndex(["2000-01-01"]), bounds) is None
    assert first_period_start(pd.DatetimeIndex(["2000-02-01"]), None) is None


@pytest.mark.parametrize("name", sorted(FIELD_REGISTRY))
def test_every_registry_field_aligns_by_its_cell_methods(name: str) -> None:
    cell_methods = FIELD_REGISTRY[name].cell_methods
    if "time: point" in cell_methods:
        expected = "point"
    elif "time:" in cell_methods:
        expected = "mean"
    else:
        # No time entry: a static field, whose value holds at every instant.
        expected = "point"

    assert time_method_for(name) == expected


def test_the_registry_states_and_fluxes_are_the_ones_expected() -> None:
    states = {"head", "watertable_elevation", "watertable_depth", "concentration"}
    fluxes = {"drain", "seepage_rate", "recharge", "release_flux", "outflow_drain"}

    assert {time_method_for(name) for name in states} == {"point"}
    assert {time_method_for(name) for name in fluxes} == {"mean"}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("discharge", "mean"),
        ("outlet_discharge", "mean"),
        ("discharge_obs", "mean"),
        ("lake_level", "point"),
        ("lake_level_obs", "point"),
        ("stage", "point"),
        ("volume", "point"),
        ("surface_area", "point"),
        ("groundwater_level", "point"),
        ("an_unknown_name", "mean"),
        (None, "mean"),
    ],
)
def test_the_calibration_variables_have_an_explicit_method(name, expected: str) -> None:
    assert time_method_for(name) == expected


def test_the_core_table_never_contradicts_the_registry() -> None:
    # The simulation layer reads the core table because it may not read the
    # registry; a name in both has to answer the same.
    shared = sorted(set(OBSERVABLE_TIME_METHODS) & set(FIELD_REGISTRY))

    assert shared
    assert {name: OBSERVABLE_TIME_METHODS[name] for name in shared} == {
        name: time_method_for(name) for name in shared
    }


def test_an_unknown_method_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown time method"):
        observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="median")
