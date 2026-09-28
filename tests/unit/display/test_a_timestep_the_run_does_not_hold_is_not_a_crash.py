"""A figure names its instant by date, and a date the run does not hold is a skip.

Measured on the Nancon. The file used to write ``timestep = 33`` for October
2002 of the monthly run, ``timestep = 1018`` for the same month of the daily
run, and a calibration phase override ``timestep = 0`` for its steady stage,
which solves one period over the whole record. Reading step 33 out of a
one-step store raised inside zarr, and ``on_error = "raise"`` turned a
converged phase into a failed run.

A date names the period that holds it on every grid: the same ``time`` draws
the same month on the monthly and the daily run, and the one period of the
steady stage. A date outside a run is a figure inapplicable to that run,
skipped with the reason, never a failure.
"""

from __future__ import annotations

import logging
import warnings

import pandas as pd
import pytest

from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning
from hydromodpy.core.logging import get_logger
from hydromodpy.display import runs as _runs
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.runs import log_render_summary, render_figure, render_figures_for_run
from hydromodpy.results.run.periods import RunPeriods

OCTOBER = "2002-10-15"


class _Figure:
    """A figure that is available and records the options it is drawn with."""

    spec = FigureSpec(name="stub", title="stub")

    def __init__(self) -> None:
        self.drawn: list[dict] = []

    def unavailable_reason(self, _sim) -> None:
        return None

    def plot(self, _sim, *, dpi=150, save_path=None, timestep=None, cmap=None, **_):
        self.drawn.append({"timestep": timestep, "cmap": cmap, **_})


class _Periods(RunPeriods):
    """The real ``run.periods`` lookups over given edges, with no catalog behind."""

    def __init__(self, edges, n_timesteps: int) -> None:
        self.edges = edges
        self._n_timesteps = n_timesteps

    def _count(self) -> int:
        return self._n_timesteps


class _Run:
    """A run as the time selector reads it: its period edges, nothing else.

    ``periods`` holds the real :meth:`RunPeriods.step_at`.
    """

    solver = "modflow6"

    def __init__(self, edges) -> None:
        self.n_timesteps = 1 if edges is None else len(edges) - 1
        self.periods = _Periods(
            None if edges is None else pd.DatetimeIndex(edges), self.n_timesteps
        )

    def has_field(self, _name: str) -> bool:
        return True

    def has_table(self, _name: str) -> bool:
        return True


MONTHLY = pd.date_range("2000-01-01", "2003-01-01", freq="MS")
DAILY = pd.date_range("2000-01-01", "2003-01-01", freq="D")
STEADY = pd.DatetimeIndex(["2000-01-01", "2003-01-01"])


@pytest.fixture
def figure(monkeypatch) -> _Figure:
    stub = _Figure()
    monkeypatch.setattr(_runs, "_get_figure", lambda _name: stub)
    return stub


def _config(**display) -> DisplayConfig:
    display.setdefault("figures", ["seepage_map"])
    return DisplayConfig(enabled=True, on_error="raise", save=False, **display)


@pytest.mark.parametrize(
    ("edges", "expected"),
    [(MONTHLY, 33), (DAILY, 1018), (STEADY, 0)],
    ids=["monthly", "daily", "one-period steady"],
)
def test_one_date_names_the_period_that_holds_it_on_every_grid(
    figure, tmp_path, edges, expected
) -> None:
    report = render_figures_for_run(_Run(edges), _config(time=OCTOBER), output_dir=tmp_path)

    assert report.rendered == ("seepage_map",)
    drawn = figure.drawn[0]
    assert drawn["timestep"] == expected
    assert "time" not in drawn
    # The same instant on the three grids: the period drawn holds the date.
    assert edges[expected] <= pd.Timestamp(OCTOBER) < edges[expected + 1]


def test_the_steady_stage_draws_the_date_with_no_phase_override(figure, tmp_path) -> None:
    # The two lines a calibration file wrote to undo an index are not needed:
    # the one period of the steady stage covers the whole record.
    cfg = _config(time=OCTOBER, figures=["seepage_map", "cross_section"])

    report = render_figures_for_run(_Run(STEADY), cfg, output_dir=tmp_path)

    assert report.rendered == ("seepage_map", "cross_section")
    assert [d["timestep"] for d in figure.drawn] == [0, 0]


def test_a_date_outside_the_run_is_skipped_with_the_record_it_holds(figure, tmp_path) -> None:
    # A phase window narrower than the record: the date is not in it.
    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")

    report = render_figures_for_run(_Run(window), _config(time=OCTOBER), output_dir=tmp_path)

    assert report.rendered == ()
    assert figure.drawn == []
    (skipped,) = report.skipped
    assert skipped.name == "seepage_map"
    assert "2002-10-15" in skipped.reason
    assert "2001-01-01 to 2002-01-01" in skipped.reason
    assert skipped.actionable is False


def test_a_date_on_a_run_without_dates_is_skipped_and_last_still_draws(figure, tmp_path) -> None:
    no_dates = _Run(None)

    dated = render_figures_for_run(no_dates, _config(time=OCTOBER), output_dir=tmp_path)
    last = render_figures_for_run(no_dates, _config(time="last"), output_dir=tmp_path)

    assert "no dates" in dated.skipped[0].reason
    assert last.rendered == ("seepage_map",)
    assert figure.drawn[0]["timestep"] == 0


def test_the_figure_time_wins_over_the_gallery_time(figure, tmp_path) -> None:
    cfg = _config(time=OCTOBER, overrides={"seepage_map": {"time": "first"}})

    render_figures_for_run(_Run(MONTHLY), cfg, output_dir=tmp_path)

    assert figure.drawn[0]["timestep"] == 0


class _Series(_Figure):
    """A figure over the whole record: its plot takes no instant."""

    def plot(self, _sim, *, dpi=150, save_path=None, **_):
        self.drawn.append(dict(_))


def test_the_gallery_time_reaches_only_the_figures_that_draw_one_instant(
    monkeypatch, tmp_path
) -> None:
    # A hydrograph draws the whole record: a gallery date must neither reach
    # it nor skip it on a run that does not hold the date.
    series = _Series()
    monkeypatch.setattr(_runs, "_get_figure", lambda _name: series)
    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")
    cfg = _config(time=OCTOBER, figures=["hydrograph"])

    report = render_figures_for_run(_Run(window), cfg, output_dir=tmp_path)

    assert report.rendered == ("hydrograph",)
    assert series.drawn == [{}]


def test_the_former_timestep_key_is_still_a_period_index(figure, tmp_path) -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="'timestep' is now called 'time'"):
        cfg = _config(overrides={"seepage_map": {"timestep": 33}})

    monthly = render_figures_for_run(_Run(MONTHLY), cfg, output_dir=tmp_path)
    steady = render_figures_for_run(_Run(STEADY), cfg, output_dir=tmp_path)

    assert monthly.rendered == ("seepage_map",)
    assert figure.drawn[0]["timestep"] == 33
    # An index names nothing on a run of another length: a skip, not a crash.
    assert steady.rendered == ()
    assert "period index 33 is out of range" in steady.skipped[0].reason


def test_a_skip_by_date_is_not_a_warning(figure, tmp_path) -> None:
    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")
    report = render_figures_for_run(_Run(window), _config(time=OCTOBER), output_dir=tmp_path)
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    summary_logger = get_logger("hydromodpy.display.runs")
    previous = summary_logger.level
    summary_logger.setLevel(logging.DEBUG)
    summary_logger.addHandler(handler)
    try:
        log_render_summary(report, destination=tmp_path)
    finally:
        summary_logger.removeHandler(handler)
        summary_logger.setLevel(previous)

    assert [r.levelname for r in records] == ["INFO", "INFO"]
    assert "seepage_map" in records[1].getMessage()


def test_one_figure_resolves_its_date_and_refuses_one_the_run_does_not_hold(figure) -> None:
    # hmp.figure and hmp viz show go through render_figure.
    render_figure("seepage_map", _Run(DAILY), time=OCTOBER)
    assert figure.drawn[0]["timestep"] == 1018

    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")
    with pytest.raises(ValueError, match="does not apply to this run: time '2002-10-15'"):
        render_figure("seepage_map", _Run(window), time=OCTOBER)


def test_one_figure_refuses_an_option_it_does_not_take(figure) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(ValueError, match="has no option 'timestep'.*time"):
            render_figure("seepage_map", _Run(MONTHLY), timestep=33)
    assert figure.drawn == []
