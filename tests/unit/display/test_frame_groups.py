"""The groups frame on the small stored run: the numbers of ``data`` and one bar per category."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import static
from hydromodpy.display.frames import groups, series
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from hydromodpy.results.run.group import RunSet
from tests._helpers.run_builders import GAUGE
from tests.unit.display._stored_run import ZONE_AREA

THEME = THEMES["default"]
ZONE = "zone:catchment"
DAYS = np.array([31, 28, 31, 30]) * 86400.0
RECHARGE = 8 * 2.0e-3 * (1 + 0.1 * np.arange(4)) / ZONE_AREA * 86400 * 1000
"""Zone recharge of each period in mm/day. The drain term is minus half of it."""


def data(run, **panel):
    return groups.data(run, PanelRequest(type="groups", **panel))


def test_budget_terms_are_period_weighted_means_that_keep_their_sign(stored_run):
    table = data(stored_run, variable="budget", station=ZONE, reduce="mean").table
    mean = np.average(RECHARGE, weights=DAYS)
    values = dict(zip(table["member"], table["value"], strict=True))
    assert values["recharge"] == pytest.approx(mean, rel=1e-4)
    assert values["drain"] == pytest.approx(-0.5 * mean, rel=1e-4)
    assert table["value"].sum() == pytest.approx(0.5 * mean, rel=1e-4)
    assert table["category"].tolist() == ["Recharge", "Drain flow"]
    top = data(stored_run, variable="recharge", station=ZONE, reduce="max").table
    assert top["value"].iloc[0] == pytest.approx(RECHARGE.max(), rel=1e-4)


def test_boxes_by_time_give_one_group_per_period_with_ordered_quantiles(stored_run):
    out = data(stored_run, variable="head", by="time")
    assert out.boxes
    # A state is stamped by its period end, but the category names the period.
    assert out.table["category"].tolist() == ["2001-01", "2001-02", "2001-03", "2001-04"]
    five = out.table[["low", "q1", "median", "q3", "high"]].to_numpy()
    assert (np.diff(five, axis=1) >= 0).all()
    assert out.table["value"].isna().all()
    assert (five[:, 2] > five[0, 2]).sum() == 3  # the head rises by one metre each period
    assert (out.table["n"] == 8).all()


def test_boxes_by_month_hold_one_value_per_month_on_four_periods(stored_run):
    # The stored run covers four months, so a month box is one value, not a spread.
    out = data(stored_run, variable="discharge", station=GAUGE, by="month")
    assert out.table["category"].tolist() == ["Jan", "Feb", "Mar", "Apr"]
    np.testing.assert_allclose(out.table["median"], [1.0, 2.0, 3.0, 2.5])
    np.testing.assert_allclose(out.table["low"], out.table["high"])
    assert (out.table["n"] == 1).all()


REFUSED = [
    ({"variable": "recharge", "station": ZONE}, "needs by"),
    ({"variable": "head", "by": "time", "stack": True}, "cannot be stacked"),
    ({"variable": "discharge", "station": GAUGE, "by": "run", "reduce": "mean"}, "run set"),
    ({"variable": "head", "station": ZONE, "reduce": "frequency"}, "frequency"),
    ({"variable": "head", "by": "time", "time": 0}, "each period"),
]


@pytest.mark.parametrize(("panel", "word"), REFUSED)
def test_a_request_that_cannot_make_a_group_is_refused(stored_run, panel, word):
    with pytest.raises(FigureNotApplicable, match=word):
        data(stored_run, **panel)


@pytest.mark.parametrize(
    ("panel", "weight"),
    [
        ({"variable": "head", "by": "time"}, "cell area"),
        ({"variable": "discharge", "station": GAUGE, "by": "month"}, "period length"),
    ],
)
def test_a_box_note_says_what_a_box_shows_and_what_weights_it(stored_run, panel, weight):
    ax = static.new_figure(THEME).axes[0]
    groups.draw(ax, data(stored_run, **panel), THEME)
    note = ax.get_xlabel().replace("\n", " ")
    assert "Box 25 to 75 %" in note and f"weighted by {weight}" in note
    assert "whiskers min to max" in note and "n = " in note


@pytest.mark.parametrize(
    ("counts", "words"), [([36, 36], "whiskers 5 to 95 %, n = 36 per"), ([3, 9], "n = 3 to 9")]
)
def test_the_whiskers_are_named_by_how_many_values_a_box_holds(counts, words):
    assert words in groups._box_note(pd.DataFrame({"n": counts}), "x").replace("\n", " ")


def test_a_budget_term_has_one_colour_in_the_stacked_series_and_in_the_bars(stored_run):
    asked = PanelRequest(type="series", variable=["budget"], station=ZONE, stack=True)
    stacked, bars = (static.new_figure(THEME).axes[0] for _ in range(2))
    series.draw(stacked, series.data(stored_run, asked), THEME)
    groups.draw(bars, data(stored_run, variable="budget", station=ZONE, reduce="mean"), THEME)
    colours = [c.patches[0].get_facecolor() for c in stacked.containers[:2]]
    assert colours == [p.get_facecolor() for p in bars.patches[:2]]
    assert [t.get_text() for t in bars.get_xticklabels()] == ["Recharge", "Drain flow"]


DRAWN = [
    {"variable": "seepage_mask", "station": ZONE},
    {"variable": "discharge", "station": GAUGE, "by": "month", "observed": True},
    {"variable": "discharge", "station": GAUGE, "by": "month", "reduce": "max"},
    {"variable": "head", "by": "time", "reduce": "mean"},
    {"variable": "budget", "station": ZONE, "reduce": "mean", "stack": True},
    {"variable": "discharge", "station": GAUGE, "reduce": "mean", "scale": "log"},
]


@pytest.mark.parametrize("panel", DRAWN)
def test_each_kind_of_group_draws_on_one_axes(stored_run, panel):
    ax = static.new_figure(THEME).axes[0]
    groups.draw(ax, data(stored_run, **panel), THEME)
    assert ax.patches or ax.lines


class Named:
    """A run under another name, every read going to the run."""

    def __init__(self, run, name):
        self._run, self.name = run, name

    def __getattr__(self, name):
        return getattr(self._run, name)


class Set(RunSet):
    def __init__(self, runs):
        self._runs, self._sim_ids = runs, [run.sim_id for run in runs]

    def __iter__(self):
        return iter(self._runs)


def test_a_run_set_is_drawn_by_run_and_a_long_list_of_names_is_turned(stored_run):
    runs = Set([Named(stored_run, f"calibration number {i}") for i in range(7)])
    out = data(runs, variable="discharge", station=GAUGE, by="run", reduce="mean")
    assert out.table["category"].tolist() == [f"calibration number {i}" for i in range(7)]
    ax = static.new_figure(THEME).axes[0]
    groups.draw(ax, out, THEME)
    labels = ax.get_xticklabels()
    assert labels[0].get_rotation() == 45 and labels[0].get_horizontalalignment() == "right"


@pytest.mark.parametrize(
    ("panel", "word"),
    [
        ({}, "needs a variable"),
        ({"variable": "head", "by": "month"}, "by = 'run' only"),
    ],
)
def test_a_groups_panel_without_a_variable_or_on_a_run_set_is_refused(stored_run, panel, word):
    subject = Set([stored_run]) if panel else stored_run
    with pytest.raises(FigureNotApplicable, match=word):
        data(subject, **panel)


def test_the_observed_record_is_a_bar_of_its_own_colour_beside_the_simulation(stored_run):
    ax = static.new_figure(THEME).axes[0]
    panel = {"variable": "discharge", "station": GAUGE, "by": "month", "reduce": "mean", "observed": True}  # fmt: skip
    groups.draw(ax, data(stored_run, **panel), THEME)
    colours = {p.get_facecolor() for p in ax.patches}
    assert len(colours) == 2 and ax.get_legend_handles_labels()[1] == ["simulated", "observed"]


def test_several_variables_by_run_are_labelled_bars_side_by_side(stored_run):
    runs = Set([Named(stored_run, "first"), Named(stored_run, "second")])
    panel = {"variable": ["recharge", "drain"], "station": ZONE, "by": "run", "reduce": "mean"}
    ax = static.new_figure(THEME).axes[0]
    groups.draw(ax, data(runs, **panel), THEME)
    assert len(ax.get_legend_handles_labels()[1]) == 2 and len(ax.patches) == 4


def test_boxes_on_a_log_axis_keep_it_and_a_short_sample_names_both_whiskers():
    assert "5 to 95 %, min to max under ten values" in groups._box_note(
        pd.DataFrame({"n": [3, 12]}), "x"
    ).replace("\n", " ")
    assert "whiskers 5 to 95 %" in groups._box_note(pd.DataFrame({"n": [12, 14]}), "x").replace("\n", " ")  # fmt: skip


def test_boxes_by_month_follow_a_log_scale_when_it_is_asked(stored_run):
    ax = static.new_figure(THEME).axes[0]
    groups.draw(ax, data(stored_run, variable="discharge", station=GAUGE, by="month", scale="log"), THEME)  # fmt: skip
    assert ax.get_yscale() == "log" and len(ax.lines) > 0
