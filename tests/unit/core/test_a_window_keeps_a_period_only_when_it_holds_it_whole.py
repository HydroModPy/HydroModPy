"""A window of days keeps a period when it holds the whole period, a state at its stamp.

The run and the calibration session read the same declared window. The run
kept a mean over a period when the whole period ``[s, e)`` lay inside it; the
session kept a pair when its END stamp did, so it scored the period before the
window and lost the last one (N1 of the audit of 2026-10-20). One rule now
serves both, written once in ``core/time``.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

from hydromodpy.core.time.period_aggregation import periods_in_window

FIRST_PERIOD = pd.Timestamp("2000-01-01")
# A monthly run over 2000-2002: each stamp closes the month before it.
STAMPS = pd.date_range("2000-02-01", "2003-01-01", freq="MS")


def _kept(mask: np.ndarray, stamps: pd.DatetimeIndex = STAMPS) -> pd.DatetimeIndex:
    return stamps[np.asarray(mask, dtype=bool)]


def test_a_mean_counts_when_its_whole_period_lies_in_the_window() -> None:
    mask = periods_in_window(
        STAMPS,
        method="mean",
        start=datetime.date(2001, 1, 1),
        end=datetime.date(2002, 12, 31),
        period_start=FIRST_PERIOD,
    )

    kept = _kept(mask)
    assert len(kept) == 24
    # January 2001 closes on 2001-02-01, December 2002 on 2003-01-01.
    assert kept[0] == pd.Timestamp("2001-02-01")
    assert kept[-1] == pd.Timestamp("2003-01-01")


def test_a_start_alone_keeps_what_the_two_bounds_keep_on_a_run_that_ends_there() -> None:
    mask = periods_in_window(
        STAMPS, method="mean", start=pd.Timestamp("2001-01-01"), period_start=FIRST_PERIOD
    )

    assert len(_kept(mask)) == 24


def test_an_end_alone_keeps_every_period_closed_by_midnight_after_it() -> None:
    mask = periods_in_window(STAMPS, method="mean", end=pd.Timestamp("2000-12-31"))

    kept = _kept(mask)
    assert len(kept) == 12
    assert kept[-1] == pd.Timestamp("2001-01-01")


def test_a_period_straddling_a_bound_is_out() -> None:
    mask = periods_in_window(
        STAMPS,
        method="mean",
        start=datetime.date(2001, 1, 15),
        end=datetime.date(2001, 3, 15),
        period_start=FIRST_PERIOD,
    )

    assert list(_kept(mask)) == [pd.Timestamp("2001-03-01")]


def test_a_state_counts_when_its_stamp_falls_in_the_window() -> None:
    mask = periods_in_window(
        STAMPS, method="point", start=datetime.date(2001, 1, 1), end=datetime.date(2002, 12, 31)
    )

    kept = _kept(mask)
    assert len(kept) == 24
    assert kept[0] == pd.Timestamp("2001-01-01")
    assert kept[-1] == pd.Timestamp("2002-12-01")


def test_a_gap_in_the_pairs_does_not_move_the_start_of_the_next_period() -> None:
    # February 2001 is missing from the pairs: March 2001 still starts on 1 March.
    paired = STAMPS.delete(STAMPS.get_loc(pd.Timestamp("2001-03-01")))

    mask = periods_in_window(
        paired,
        method="mean",
        start=datetime.date(2001, 3, 1),
        end=datetime.date(2001, 3, 31),
        grid=STAMPS,
        period_start=FIRST_PERIOD,
    )

    assert list(_kept(mask, paired)) == [pd.Timestamp("2001-04-01")]


def test_a_steady_stamp_counts_when_its_period_lies_in_the_window() -> None:
    stamp = pd.DatetimeIndex([pd.Timestamp("2003-01-01")])

    inside = periods_in_window(
        stamp,
        method="mean",
        start=datetime.date(2000, 1, 1),
        end=datetime.date(2002, 12, 31),
        period_start=FIRST_PERIOD,
    )
    cut = periods_in_window(
        stamp, method="mean", start=datetime.date(2001, 1, 1), period_start=FIRST_PERIOD
    )

    assert inside.tolist() == [True]
    assert cut.tolist() == [False]


def test_utc_stamps_are_read_on_the_naive_utc_clock() -> None:
    aware = STAMPS.tz_localize("UTC")

    mask = periods_in_window(
        aware,
        method="mean",
        start=datetime.date(2001, 1, 1),
        end=datetime.date(2002, 12, 31),
        period_start=FIRST_PERIOD,
    )

    assert int(np.count_nonzero(mask)) == 24


def test_no_bound_keeps_everything() -> None:
    mask = periods_in_window(STAMPS, method="mean")

    assert bool(np.all(mask))
