"""The transient-stage hydrograph, on the axis the second stage is scored on.

The run side is driven exactly as a plain run drives it: one simulated
discharge series at the catchment pseudo-station, observations under their own
gauge ids. The two calibration notions, the scoring window and the score, are
handed to ``render()`` because ``display`` may not import ``calibration``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures.hydrograph_log_nse import (
    SPLIT_COLORS,
    HydrographLogNseFigure,
)

STATION = "_catchment"


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


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
        return pd.DataFrame(
            {
                "station_id": ["J7000610"] * len(self.index),
                "datetime": self.index,
                "value": self._observed,
            }
        )


def _run(**kwargs) -> _Run:
    """A four-day run whose observed and simulated series both stay positive."""
    return _Run([2.0, 1.0, 0.5, 1.5], observed=[1.8, 1.1, 0.6, 1.4], **kwargs)


def _line(ax, label_prefix: str):
    return next(line for line in ax.lines if str(line.get_label()).startswith(label_prefix))


def _labels(ax) -> list[str]:
    return [str(line.get_label()) for line in ax.lines]


def _note(ax) -> str:
    return "\n".join(text.get_text() for text in ax.texts)


def _relative_luminance(color: str) -> float:
    """Perceived brightness of one colour, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


# --------------------------------------------------------------------------- #
# the hydrograph itself
# --------------------------------------------------------------------------- #


def test_draws_simulated_and_observed_on_a_log_axis(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_run(), ax)

    try:
        assert ax.get_yscale() == "log"
        assert ax.get_ylabel() == "Discharge (m³/s)"
        assert ax.get_xlabel() == "Date"
        assert _line(ax, "simulated total").get_ydata().tolist() == [2.0, 1.0, 0.5, 1.5]
        assert _line(ax, "observed").get_ydata().tolist() == [1.8, 1.1, 0.6, 1.4]
        assert "cheze-transient" in ax.get_title()
    finally:
        mpl.close(fig)


def test_draws_the_hydrograph_of_a_run_without_observations(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_Run([2.0, 1.0, 0.5, 1.5]), ax)

    try:
        assert _line(ax, "simulated total").get_ydata().tolist() == [2.0, 1.0, 0.5, 1.5]
        assert not [label for label in _labels(ax) if label.startswith("observed")]
        assert "no observed" in _note(ax)
    finally:
        mpl.close(fig)


def test_a_failed_timestep_breaks_the_line_instead_of_reading_as_a_zero(mpl) -> None:
    run = _Run([2.0, float("nan"), 0.5, 1.5], observed=[1.8, 1.1, 0.6, 1.4])
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        drawn = _line(ax, "simulated total").get_ydata()
        assert np.isnan(drawn[1])
        assert drawn[0] == 2.0
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the drainage / runoff split
# --------------------------------------------------------------------------- #


def test_splits_drainage_and_runoff_as_two_extra_lines(mpl) -> None:
    run = _run(
        components={
            "drainage": [1.5, 0.9, 0.45, 1.0],
            "runoff": [0.5, 0.1, 0.05, 0.5],
        }
    )
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        assert _line(ax, "drainage").get_ydata().tolist() == [1.5, 0.9, 0.45, 1.0]
        assert _line(ax, "runoff").get_ydata().tolist() == [0.5, 0.1, 0.05, 0.5]
    finally:
        mpl.close(fig)


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


def test_says_when_no_split_is_available(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_run(), ax)

    try:
        assert not [label for label in _labels(ax) if label.startswith(("drainage", "runoff"))]
        assert "no drainage / runoff split" in _note(ax)
    finally:
        mpl.close(fig)


def test_a_split_component_on_a_foreign_clock_is_reported_absent(mpl) -> None:
    """A component reindexed onto another index carries no sample at all.

    It must collapse to the "no split" annotation, not to two legend entries
    a reader would take for a split that simply sits off the panel.
    """
    run = _run()
    run._series["drainage"] = pd.Series(
        [1.5, 0.9, 0.45, 1.0], index=pd.date_range("2015-01-01", periods=4, freq="D")
    )
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        assert not [label for label in _labels(ax) if label.startswith(("drainage", "runoff"))]
        assert "no drainage / runoff split" in _note(ax)
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
        assert "no finite sample" in _note(ax)
    finally:
        mpl.close(fig)


def test_says_when_the_simulated_series_is_empty(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_Run([], n_days=0), ax)

    try:
        assert "no finite sample" in _note(ax)
    finally:
        mpl.close(fig)


def test_the_three_curves_stay_apart_in_greyscale() -> None:
    luminances = sorted(_relative_luminance(color) for color in SPLIT_COLORS.values())
    gaps = [high - low for low, high in zip(luminances[:-1], luminances[1:], strict=False)]
    assert min(gaps) > 0.1


# --------------------------------------------------------------------------- #
# the log floor
# --------------------------------------------------------------------------- #


def test_non_positive_samples_land_on_the_floor_and_are_counted(mpl) -> None:
    # The observed median is 1.0, so the floor is 0.01: the same offset the
    # metric adds before its logarithm.
    run = _Run([2.0, 0.0, -0.5, 1.0], observed=[1.0, 1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        drawn = _line(ax, "simulated total").get_ydata()
        assert drawn.tolist() == [2.0, 0.01, 0.01, 1.0]
        note = _note(ax)
        assert "0.01" in note
        assert "simulated total 2" in note
        assert "of 4 samples" in note
        assert _line(ax, "on the log floor").get_ydata().tolist() == [0.01, 0.01]
    finally:
        mpl.close(fig)


def test_an_explicit_floor_overrides_the_metric_offset(mpl) -> None:
    run = _Run([2.0, 0.0, -0.5, 1.0], observed=[1.0, 1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax, floor=0.1)

    try:
        assert _line(ax, "simulated total").get_ydata().tolist() == [2.0, 0.1, 0.1, 1.0]
    finally:
        mpl.close(fig)


def test_the_floor_stays_inside_the_drawn_range(mpl) -> None:
    run = _Run([2.0, 0.0, -0.5, 1.0], observed=[1.0, 1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        bottom, top = ax.get_ylim()
        assert bottom < 0.01
        assert top > 2.0
    finally:
        mpl.close(fig)


def test_a_component_of_the_wrong_length_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="3 samples"):
            HydrographLogNseFigure().render(_run(), ax, drainage=np.array([1.0, 0.9, 0.5]))
    finally:
        mpl.close(fig)


def test_no_floor_line_when_every_sample_is_positive(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_run(), ax)

    try:
        assert not [label for label in _labels(ax) if label.startswith("on the log floor")]
        assert "log floor" not in _note(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the scoring window and the score
# --------------------------------------------------------------------------- #


def test_shades_the_scoring_window_and_counts_the_scored_samples(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(
        _run(),
        ax,
        scoring_window=("2011-01-02", "2011-01-03"),
    )

    try:
        spans = [patch for patch in ax.patches if "scoring window" in str(patch.get_label())]
        assert len(spans) == 1
        note = _note(ax)
        assert "2011-01-02" in note
        assert "2 of 4 samples scored" in note
    finally:
        mpl.close(fig)


def test_annotates_the_nse_log_value(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_run(), ax, nse_log=0.8123)

    try:
        assert "NSElog = 0.812" in _note(ax)
    finally:
        mpl.close(fig)


def test_says_when_neither_the_window_nor_the_score_was_given(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_run(), ax)

    try:
        note = _note(ax)
        assert "no scoring window" in note
        assert "NSElog not given" in note
        assert not [patch for patch in ax.patches if "scoring window" in str(patch.get_label())]
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


def test_registered_under_its_name() -> None:
    figure = get_figure("hydrograph_log_nse")

    assert isinstance(figure, HydrographLogNseFigure)
    assert figure.spec.kind == "comparison"
