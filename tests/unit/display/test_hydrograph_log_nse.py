"""The log-NSE hydrograph and the comparison figures that print the run's score."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.hydrograph_log_nse import HydrographLogNseFigure
from hydromodpy.display.figures.scatter_one_to_one import ScatterOneToOne
from hydromodpy.results.record.manifest import MetricRow
from hydromodpy.results.storage.run_store import RunStore

# The transient-stage hydrograph, on the axis the second stage is scored on.
#
# The run side is driven exactly as a plain run drives it: one simulated
# discharge series at the catchment pseudo-station, observations under their own
# gauge ids. The scoring window and the score are the ones the run recorded on
# ``[metrics] window``, read from the run: no option of the figure types them.

STATION = "catchment"


class _Run:
    """A Run holding only what this figure reads: series and observations."""

    def __init__(
        self,
        discharge: list[float] | None,
        *,
        observed: list[float] | None = None,
        components: dict[str, list[float]] | None = None,
        n_days: int = 4,
        name: str = "cheze-transient",
    ) -> None:
        self.sim_id = "sim-cheze"
        self.name = name
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


def _run(**kwargs) -> _Run:
    """A four-day run whose observed and simulated series both stay positive."""
    return _Run([2.0, 1.0, 0.5, 1.5], observed=[1.8, 1.1, 0.6, 1.4], **kwargs)


def _scored(run: _Run, *, nse_log: float = 0.8123) -> _Run:
    """The run with the score the derive step records: NSElog on 2 and 3 January."""
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


def _line(ax, label_prefix: str):
    return next(line for line in ax.lines if str(line.get_label()).startswith(label_prefix))


def _labels(ax) -> list[str]:
    return [str(line.get_label()) for line in ax.lines]


def _note(ax) -> str:
    return "\n".join(text.get_text() for text in ax.texts)


# --------------------------------------------------------------------------- #
# the hydrograph itself
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# the drainage / runoff split
# --------------------------------------------------------------------------- #


def test_takes_the_split_from_render_arguments_over_the_run(mpl) -> None:
    run = _run(components={"drainage": [9.0, 9.0, 9.0, 9.0]})
    given = pd.Series([1.5, 0.9, 0.45, 1.0], index=run.index)
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax, drainage=given)

    try:
        assert _line(ax, "drainage").get_ydata().tolist() == [1.5, 0.9, 0.45, 1.0]
    finally:
        mpl.close(fig)


def test_completes_the_split_by_difference_and_says_so(mpl) -> None:
    run = _run(components={"drainage": [1.5, 0.9, 0.45, 1.0]})
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        runoff = _line(ax, "runoff")
        assert runoff.get_ydata() == pytest.approx([0.5, 0.1, 0.05, 0.5])
        assert "by difference" in str(runoff.get_label())
    finally:
        mpl.close(fig)


def test_the_other_component_still_follows_by_difference(mpl) -> None:
    run = _run(components={"runoff": [0.5, 0.1, 0.05, 0.5]})
    run._series["drainage"] = pd.Series(
        [np.nan] * 4, index=pd.date_range("2015-01-01", periods=4, freq="D")
    )
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        drainage = _line(ax, "drainage")
        assert drainage.get_ydata() == pytest.approx([1.5, 0.9, 0.45, 1.0])
        assert "by difference" in str(drainage.get_label())
    finally:
        mpl.close(fig)


def test_says_when_the_simulated_series_holds_no_finite_sample(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_Run([float("nan")] * 4), ax)

    try:
        assert "no simulated discharge value" in _note(ax)
    finally:
        mpl.close(fig)


def test_says_when_the_simulated_series_is_empty(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_Run([], n_days=0), ax)

    try:
        assert "no simulated discharge value" in _note(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the log floor
# --------------------------------------------------------------------------- #


def test_an_explicit_floor_overrides_the_metric_offset(mpl) -> None:
    run = _Run([2.0, 0.0, -0.5, 1.0], observed=[1.0, 1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax, floor=0.1)

    try:
        assert _line(ax, "simulated total").get_ydata().tolist() == [2.0, 0.1, 0.1, 1.0]
    finally:
        mpl.close(fig)


def test_a_component_of_the_wrong_length_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="3 samples"):
            HydrographLogNseFigure().render(_run(), ax, drainage=np.array([1.0, 0.9, 0.5]))
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the scoring window and the score
# --------------------------------------------------------------------------- #


def test_annotates_the_nse_log_the_run_recorded(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_scored(_run()), ax)

    try:
        assert "NSElog = 0.812" in _note(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# availability
# --------------------------------------------------------------------------- #


def test_available_on_a_plain_run() -> None:
    assert HydrographLogNseFigure().unavailable_reason(_run()) is None


def test_unavailable_only_when_the_discharge_series_is_missing() -> None:
    figure = HydrographLogNseFigure()

    reason = figure.unavailable_reason(_Run(None, observed=[1.0, 1.0, 1.0, 1.0]))

    assert reason is not None
    assert "discharge" in reason


# The log floor of the figure is the epsilon of the score, read on the scored sample.
#
# The floor was one percent of the median of every observed station over the whole
# series, before the scoring window. The score takes its epsilon on the pairs it
# scores, so the two disagreed whenever the flow before the window differed from
# the flow inside it.


def test_the_floor_is_read_on_the_samples_the_score_read(mpl) -> None:  # noqa: F811
    # The window holds the last two days, observed at 1.0; the whole series
    # has a median of 50.5.
    run = _scored(_Run([2.0, 3.0, 0.0, 0.0], observed=[100.0, 100.0, 1.0, 1.0]))
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        floor = _line(ax, "on the log floor").get_ydata()
        assert floor.tolist() == pytest.approx([0.01, 0.01])
    finally:
        mpl.close(fig)


# The comparison figures print the score the run recorded, never one of their own.
#
# ``scatter_one_to_one`` scored the pairs it drew, on every shared timestamp,
# spin-up included; ``hydrograph_log_nse`` printed whatever window and NSElog
# were typed beside it. Both now read the scores the run recorded on
# ``[metrics] window``, with that window and its sample count, from the seal or,
# before it, from the facts of the run's store.

# Each stamp closes the month before it, as a run stamps its periods.
STAMPS = pd.date_range("2000-02-01", periods=36, freq="MS")


GAUGE = "NANCON"


class _ScoredRun:
    """Three monthly years and their gauge, scored on 2001-2002 as the derive step does."""

    sim_id = "sim-nancon"
    name = "nancon"

    def __init__(self, *, scored: bool = True) -> None:
        months = np.arange(STAMPS.size, dtype=float)
        self._sim = pd.Series(1.0 + 0.5 * np.cos(2.0 * np.pi * months / 12.0), index=STAMPS)
        self._obs = self._sim * 1.1 + 0.05
        rows = [
            MetricRow(
                station=GAUGE,
                variable="discharge",
                metric=metric,
                value=value,
                window_start=datetime.date(2001, 1, 1),
                window_end=datetime.date(2002, 12, 31),
                n_samples=24,
                metric_rule_version="1",
            ).model_dump()
            for metric, value in (("nse", 0.913), ("nse_log", 0.876), ("rmse", 0.12))
        ]
        columns = list(MetricRow.model_fields)
        self.metrics = pd.DataFrame(rows if scored else [], columns=columns)

    def has_table(self, table: str) -> bool:
        return table == "timeseries"

    def has_field(self, variable: str, **_) -> bool:
        return False

    def stations(self, variable: str) -> list[str]:
        return ["catchment"] if variable == "discharge" else []

    def timeseries(self, variable: str, *, station: str | None = None, **_) -> pd.Series:
        if variable != "discharge":
            raise KeyError(variable)
        return self._sim.copy()

    def observed(self, variable: str, station: str | None = None, **_) -> pd.DataFrame:
        days = pd.date_range("2000-01-01", STAMPS[-1], freq="D")
        daily = self._obs.reindex(days, method="bfill")
        return pd.DataFrame(
            {
                "station_id": [GAUGE] * days.size,
                "datetime": days,
                "variable": [variable] * days.size,
                "value": daily.to_numpy(),
            }
        )


def _text(ax) -> str:
    return "\n".join(text.get_text() for text in ax.texts)


def test_the_scatter_prints_the_score_of_the_run(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(_ScoredRun(), ax)

    text = _text(ax)
    assert "NSE 0.913" in text
    assert "RMSE 0.12" in text
    assert "scored 2001-01-01 to 2002-12-31, n 24" in text
    mpl.close(fig)


def test_the_scatter_draws_the_pairs_the_score_left_out_apart(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(_ScoredRun(), ax)

    scored, unscored = (
        len(collection.get_offsets())
        for collection in sorted(
            ax.collections, key=lambda c: str(c.get_label()) != "not scored", reverse=True
        )
    )
    assert scored == 24
    assert unscored > 0
    mpl.close(fig)


def test_the_scatter_of_an_unscored_run_prints_no_number(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(_ScoredRun(scored=False), ax)

    text = _text(ax)
    assert "holds no score" in text
    assert "NSE" not in text
    mpl.close(fig)


class _Store(RunStore):
    """A store reduced to its facts, as the display step opens a run before the seal."""

    def __init__(self, metrics: list[MetricRow]) -> None:
        self._facts = SimpleNamespace(metrics=metrics)


def test_a_run_on_its_store_reads_the_facts_before_the_seal() -> None:
    from hydromodpy.results.run.sealed import metrics_of

    run = SimpleNamespace(
        _catalog_handle=_Store([MetricRow(station=GAUGE, metric="nse", value=0.5)])
    )

    frame = metrics_of(run)

    assert frame[["station", "metric", "value"]].to_numpy().tolist() == [[GAUGE, "nse", 0.5]]
