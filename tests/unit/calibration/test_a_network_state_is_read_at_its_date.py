"""A network output read in one state reads the state its ``time`` names.

``time`` is ``"last"``, ``"first"`` or a date, and a date reads the period
``[s, e)`` that holds it, as :mod:`hydromodpy.core.time.selection` resolves
it. The backend serves the whole stack for a date, and the extraction has to
serve the criterion that one row, not the last one it was given. The trial
context is faked and everything it feeds is real: the V-valley mesh, a mapped
network read off disk, and a monthly release stack whose network moves over
the year.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibOutputNetwork, validate_calib_output
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.observable_scoring import (
    network_state_period,
    network_state_stamp,
)
from hydromodpy.calibration.metrics.solver_extract import extract_outputs, network_state_row
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.core.time.selection import TimeSelectionError
from tests.unit.calibration.test_the_two_bound_mode_scores_the_years_of_its_window import (
    SPIN_UP_RUN,
    _fake_ctx,
    _stack,
    _StackAdapter,
    _thresholds,
    bench,  # noqa: F401 (fixture)
    mapped,  # noqa: F401 (fixture)
)

pytest.importorskip("geopandas")

MONTHS = pd.date_range("2000-01-01", periods=37, freq="MS")
"""The edges of a monthly run over 2000-2002: 36 periods."""


def _one_state(mapped, time: str = "last"):  # noqa: F811
    return validate_calib_output(
        {
            "support": "network",
            "stream_geometry_path": str(mapped),
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
            "time": time,
        }
    )


def _scored(monkeypatch, bench, mapped, stack, bounds, time):  # noqa: F811
    ctx = _fake_ctx(bench, bounds)
    adapter = _StackAdapter(stack)
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    return extract_outputs(ctx, {"net": _one_state(mapped, time)}).diagnostics


class TestTheDeclaration:
    def test_a_date_is_accepted_beside_first_and_last(self) -> None:
        for time in ("last", "first", "2002-10-15"):
            assert CalibOutputNetwork(stream_geometry_path="n.gpkg", time=time).time == time

    def test_a_bare_toml_date_is_kept_as_its_iso_spelling(self) -> None:
        output = CalibOutputNetwork(stream_geometry_path="n.gpkg", time=datetime.date(2002, 10, 15))
        assert output.time == "2002-10-15"

    @pytest.mark.parametrize("time", ["all", ["2002-01-01"], "October"])
    def test_what_names_no_single_state_is_refused(self, time) -> None:
        with pytest.raises(ValidationError, match="network"):
            CalibOutputNetwork(stream_geometry_path="n.gpkg", time=time)

    def test_the_extent_table_still_takes_no_time(self) -> None:
        with pytest.raises(ValidationError, match="extent"):
            CalibOutputNetwork(stream_geometry_path="n.gpkg", time="2002-10-15", extent={})


class TestWhichPeriodADateReads:
    def test_a_date_reads_the_month_that_holds_it(self) -> None:
        assert network_state_period("2002-10-15", MONTHS, n_periods=36) == 33
        assert network_state_period("2002-10-01", MONTHS, n_periods=36) == 33

    def test_first_and_last_read_the_ends(self) -> None:
        assert network_state_period("first", MONTHS, n_periods=36) == 0
        assert network_state_period("last", MONTHS, n_periods=36) == 35

    def test_a_steady_period_holds_every_date_of_its_window(self) -> None:
        steady = (pd.Timestamp("2000-01-01"), pd.Timestamp("2003-01-01"))
        for date in ("2000-01-01", "2002-10-15", "2002-12-31"):
            assert network_state_period(date, steady, n_periods=1) == 0

    def test_one_state_without_dates_is_served_to_any_selector(self) -> None:
        assert network_state_period("2002-10-15", None, n_periods=1) == 0

    def test_a_date_outside_the_run_is_refused(self) -> None:
        with pytest.raises(TimeSelectionError, match="outside the record"):
            network_state_period("2004-01-15", MONTHS, n_periods=36)

    def test_the_state_is_stamped_at_the_end_of_its_period(self) -> None:
        assert network_state_stamp("2002-10-15", MONTHS) == pd.Timestamp("2002-11-01")
        assert network_state_stamp("last", MONTHS) == pd.Timestamp("2003-01-01")
        assert network_state_stamp("last", None) is None


class TestTheRowServed:
    def _stack(self) -> ObservableResult:
        values = np.arange(36, dtype=float)[:, None] * np.ones((1, 4))
        return ObservableResult(request_id="net", values=values, units="m3 s-1", times=MONTHS[1:])

    def test_a_date_is_served_its_own_row(self) -> None:
        output = CalibOutputNetwork(stream_geometry_path="n.gpkg", time="2002-10-15")
        row, index = network_state_row("net", output, self._stack(), tuple(MONTHS))
        assert index == 33
        assert np.asarray(row.values).tolist() == [[33.0] * 4]
        assert pd.DatetimeIndex(row.times).tolist() == [pd.Timestamp("2002-11-01")]

    def test_the_stamps_date_the_stack_when_the_grid_does_not(self) -> None:
        output = CalibOutputNetwork(stream_geometry_path="n.gpkg", time="2001-03-31")
        row, index = network_state_row("net", output, self._stack(), None)
        assert index == 14
        assert np.asarray(row.values)[0, 0] == 14.0

    def test_one_state_is_served_as_it_came(self) -> None:
        output = CalibOutputNetwork(stream_geometry_path="n.gpkg", time="2002-10-15")
        one = ObservableResult(request_id="net", values=np.ones(4), units="m3 s-1")
        row, index = network_state_row("net", output, one, None)
        assert row is one
        assert index is None

    def test_a_date_on_an_undated_stack_is_refused_by_name(self) -> None:
        output = CalibOutputNetwork(stream_geometry_path="n.gpkg", time="2002-10-15")
        undated = ObservableResult(request_id="net", values=np.ones((3, 4)), units="m3 s-1")
        with pytest.raises(ObjectiveError, match="Output 'net': time = '2002-10-15'"):
            network_state_row("net", output, undated, None)


class TestTheStateScored:
    """The criterion scores the state the date names, and no other."""

    def test_a_date_scores_what_that_month_alone_scores(self, monkeypatch, bench, mapped) -> None:  # noqa: F811
        thresholds = _thresholds(3)
        october = 12 + 9  # October 2001, the 22nd month of the run
        dated = _scored(
            monkeypatch, bench, mapped, _stack(bench, thresholds), SPIN_UP_RUN, "2001-10-15"
        )
        alone = _scored(
            monkeypatch,
            bench,
            mapped,
            _stack(bench, thresholds[october : october + 1]),
            None,
            "last",
        )
        assert dated["net.D_so"] == pytest.approx(alone["net.D_so"])
        assert dated["net.D_os"] == pytest.approx(alone["net.D_os"])
        assert dated["net.n_network_sim"] == alone["net.n_network_sim"]

    def test_the_date_is_not_the_last_state(self, monkeypatch, bench, mapped) -> None:  # noqa: F811
        stack = _stack(bench, _thresholds(3))
        dated = _scored(monkeypatch, bench, mapped, stack, SPIN_UP_RUN, "2001-10-15")
        last = _scored(monkeypatch, bench, mapped, stack, SPIN_UP_RUN, "last")
        assert dated["net.n_network_sim"] != last["net.n_network_sim"]

    def test_a_date_the_run_does_not_hold_stops_the_trial(self, monkeypatch, bench, mapped) -> None:  # noqa: F811
        with pytest.raises(ObjectiveError, match="outside the record"):
            _scored(
                monkeypatch, bench, mapped, _stack(bench, _thresholds(3)), SPIN_UP_RUN, "2005-06-01"
            )
