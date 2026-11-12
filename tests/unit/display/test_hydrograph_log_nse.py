"""Hydrograph of a run on the log-NSE axis, with discharge in m3/s and the score the run recorded.

The simulated total is split into drainage and runoff, and the log floor is
the epsilon of the score, read on the scored sample. The run side is driven
as a plain run drives it, with the window and the NSElog taken from the run.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.hydrograph_log_nse import HydrographLogNseFigure

STATION = "catchment"


class Run:
    """A Run holding only what this figure reads, series and observations."""

    def __init__(
        self,
        discharge: list[float] | None,
        *,
        observed: list[float] | None = None,
        components: dict[str, list[float]] | None = None,
        n_days: int = 4,
    ) -> None:
        self.sim_id = "sim-cheze"
        self.name = "cheze-transient"
        self.index = pd.date_range("2011-01-01", periods=n_days, freq="D")
        self._series: dict[str, pd.Series] = {}
        if discharge is not None:
            self._series["discharge"] = pd.Series(discharge, index=self.index)
        for variable, values in (components or {}).items():
            self._series[variable] = pd.Series(values, index=self.index)
        self._observed = observed

    def has_table(self, table: str) -> bool:
        return table == "timeseries"

    def has_field(self, variable: str, **_) -> bool:
        return False

    def stations(self, variable: str) -> list[str]:
        return [STATION] if variable in self._series else []

    def timeseries(self, variable: str, *, station: str | None = None, **_) -> pd.Series:
        if variable not in self._series:
            raise KeyError(f"No timeseries for var={variable}, station={station}")
        return self._series[variable]

    def observed(self, variable: str, station: str | None = None, period=None) -> pd.DataFrame:
        if self._observed is None:
            raise ValueError(f"No observations for variable={variable}")
        # The record is stamped at the day each simulated stamp closes, one
        # day before that stamp.
        return pd.DataFrame(
            {
                "station_id": ["J7000610"] * len(self.index),
                "datetime": self.index.shift(-1, freq="D"),
                "value": self._observed,
            }
        )


def four_day_run(**kwargs) -> Run:
    """A four-day run whose observed and simulated series both stay positive."""
    return Run([2.0, 1.0, 0.5, 1.5], observed=[1.8, 1.1, 0.6, 1.4], **kwargs)


def scored(run: Run, *, nse_log: float = 0.8123) -> Run:
    """The run with the score the derive step records, NSElog on 2 and 3 January."""
    run.metrics = pd.DataFrame(
        [
            {
                "station": "J7000610",
                "variable": "discharge",
                "metric": "nse_log",
                "value": nse_log,
                "window_start": datetime.date(2011, 1, 2),
                "window_end": datetime.date(2011, 1, 3),
                "n_samples": 2,
                "metric_rule_version": "1",
            }
        ]
    )
    return run


def line(ax, label_prefix: str):
    return next(line for line in ax.lines if str(line.get_label()).startswith(label_prefix))


def note(ax) -> str:
    return "\n".join(text.get_text() for text in ax.texts)


def test_split_from_render_arguments_wins_over_the_run(mpl) -> None:
    run = four_day_run(components={"drainage": [9.0, 9.0, 9.0, 9.0]})
    given = pd.Series([1.5, 0.9, 0.45, 1.0], index=run.index)
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax, drainage=given)

    assert line(ax, "drainage").get_ydata().tolist() == [1.5, 0.9, 0.45, 1.0]


def test_runoff_completes_the_split_by_difference(mpl) -> None:
    run = four_day_run(components={"drainage": [1.5, 0.9, 0.45, 1.0]})
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    runoff = line(ax, "runoff")
    assert runoff.get_ydata() == pytest.approx([0.5, 0.1, 0.05, 0.5])
    assert "by difference" in str(runoff.get_label())


def test_drainage_completes_the_split_by_difference(mpl) -> None:
    run = four_day_run(components={"runoff": [0.5, 0.1, 0.05, 0.5]})
    run._series["drainage"] = pd.Series(
        [np.nan] * 4, index=pd.date_range("2015-01-01", periods=4, freq="D")
    )
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    drainage = line(ax, "drainage")
    assert drainage.get_ydata() == pytest.approx([1.5, 0.9, 0.45, 1.0])
    assert "by difference" in str(drainage.get_label())


NO_SAMPLE_RUNS = [
    pytest.param(Run([float("nan")] * 4), id="no finite sample"),
    pytest.param(Run([], n_days=0), id="empty series"),
]


@pytest.mark.parametrize("run", NO_SAMPLE_RUNS)
def test_says_when_the_simulation_holds_no_value(mpl, run) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    assert "no simulated discharge value" in note(ax)


def test_explicit_floor_overrides_the_metric_offset(mpl) -> None:
    run = Run([2.0, 0.0, -0.5, 1.0], observed=[1.0, 1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax, floor=0.1)

    assert line(ax, "simulated total").get_ydata().tolist() == [2.0, 0.1, 0.1, 1.0]


def test_floor_is_read_on_the_scored_samples(mpl) -> None:
    # The window holds the last two days, observed at 1.0 m3/s, while the whole
    # series has a median of 50.5. The floor is one percent of the scored median.
    run = scored(Run([2.0, 3.0, 0.0, 0.0], observed=[100.0, 100.0, 1.0, 1.0]))
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    floor = line(ax, "on the log floor").get_ydata()
    assert floor.tolist() == pytest.approx([0.01, 0.01])


def test_annotates_the_recorded_nse_log(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(scored(four_day_run()), ax)

    assert "NSElog = 0.812" in note(ax)


def test_available_on_a_plain_run() -> None:
    assert HydrographLogNseFigure().unavailable_reason(four_day_run()) is None


def test_unavailable_without_a_discharge_series() -> None:
    reason = HydrographLogNseFigure().unavailable_reason(Run(None, observed=[1.0] * 4))

    assert reason is not None
    assert "discharge" in reason


def test_refuses_a_component_of_the_wrong_length(mpl) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match="3 samples"):
        HydrographLogNseFigure().render(four_day_run(), ax, drainage=np.array([1.0, 0.9, 0.5]))
