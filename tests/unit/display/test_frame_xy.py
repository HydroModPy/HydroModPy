"""The xy frame on the small stored run: the pairs of ``data`` and what ``draw`` puts on the axes."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import static
from hydromodpy.display.frames import xy
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable, read_observed, read_series
from hydromodpy.display.theme import THEMES
from hydromodpy.results.session.descriptor import ParameterBound
from tests._helpers.run_builders import GAUGE
from tests.unit.display._calibration_journal import K_BOUNDS, journal_session

THEME = THEMES["default"]
ZONE = "zone:catchment"


def data(run, **panel):
    return xy.data(run, PanelRequest(type="xy", **panel))


def test_simulated_against_observed_gives_the_observed_pairs(stored_run):
    out = data(stored_run, variable=["discharge"], station=GAUGE, observed=True)
    seen = read_observed(stored_run, "discharge", station=GAUGE).dropna()
    sim = read_series(stored_run, "discharge", station=GAUGE).loc[seen.index]
    np.testing.assert_allclose(out.table["x"], seen.to_numpy())
    np.testing.assert_allclose(out.table["y"], sim.to_numpy())
    assert out.x_label.startswith("Observed ") and out.y_label.startswith("Simulated ")
    assert list(out.table["key"]) == list(seen.index)
    two = data(stored_run, variable=["discharge", "rainfall"], station=GAUGE)
    np.testing.assert_allclose(two.table["y"], 3.0 - two.table["x"])
    assert list(two.table["key"]) == list(read_series(stored_run, "discharge", station=GAUGE).index)


def test_two_fields_give_one_row_per_cell_of_the_zone(stored_run):
    out = data(stored_run, variable=["recharge", "drain"], station=ZONE)
    assert len(out.table) == 8 and out.table["key"].dtype == np.int64
    assert out.table["station"].isna().all()
    np.testing.assert_allclose(out.table["y"], -0.5 * out.table["x"], rtol=1e-6)


@pytest.mark.parametrize(
    ("panel", "text"),
    [
        (dict(variable=["head", "discharge"], station=GAUGE), "series and a field"),
        (dict(variable=["recharge", "drain"], station=GAUGE), "not a zone"),
        (dict(variable=["recharge", "drain"], station=ZONE, time=[0, 2]), "one instant"),
        (dict(variable=["discharge", "rainfall"], station=GAUGE, observed=True), "not both"),
        (dict(variable=["discharge"], station=GAUGE, observed=True, layer=0), "layer"),
        (dict(variable=["discharge"], station=GAUGE), "two variables"),
        (dict(variable=["recharge", "drain"], station=ZONE, scores=True), "scores"),
        (dict(variable=["discharge"], station=[GAUGE], observed=True), "list of stations"),
        (dict(variable=["discharge"], station=GAUGE, observed=True, against="observed"), "against"),
    ],
)
def test_a_pair_that_cannot_be_matched_is_refused(stored_run, panel, text):
    with pytest.raises(FigureNotApplicable, match=text):
        data(stored_run, **panel)


def test_a_log_axis_drops_the_rows_at_zero_or_below_and_says_so(stored_run):
    ok = data(stored_run, variable=["rainfall", "discharge"], station=GAUGE, scale="log")
    assert ok.log_x and ok.log_y and (ok.table[["x", "y"]] > 0).all().all()
    assert len(ok.table) == 3 and ok.dropped == pytest.approx(0.25)  # no rain in March
    ax = static.new_figure(THEME).axes[0]
    xy.draw(ax, ok, THEME)
    assert [t.get_text() for t in ax.texts] == ["Not shown: 25.0% of the points at or below zero"]
    with pytest.raises(FigureNotApplicable, match="both values"):
        data(stored_run, variable=["recharge", "drain"], station=ZONE, scale="log")


def test_draw_adds_the_one_to_one_line_the_scores_and_lighter_points_outside_the_window(
    stored_run,
):
    out = data(
        stored_run, variable=["discharge"], station=GAUGE, observed=True,
        reference=["one_to_one", "zero"], scores=True,
    )  # fmt: skip
    ax = static.new_figure(THEME).axes[0]
    xy.draw(ax, out, THEME)
    assert len(ax.collections) == 1 and len(ax.lines) == 2 and len(ax.texts) == 1
    assert ax.get_xlim() == ax.get_ylim() and ax.get_xlabel() == out.x_label
    stored = stored_run.metrics
    stored = stored[(stored["variable"] == "discharge") & (stored["station"] == GAUGE)]
    assert out.scores["value"].tolist() == stored["value"].tolist()
    assert out.window == (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"))  # not the run
    assert "Outside scoring window" in ax.get_legend_handles_labels()[1]
    window = (pd.Timestamp("2001-02-01"), pd.Timestamp("2001-03-01"))
    ax = static.new_figure(THEME).axes[0]
    xy.draw(ax, dataclasses.replace(out, window=window), THEME)
    assert len(ax.collections) == 2 and sum(len(c.get_offsets()) for c in ax.collections) == 3
    assert ax.collections[0].get_alpha() > ax.collections[1].get_alpha()


def trial_rows(parameters):
    """One row per trial, ``parameters`` giving the values of each trial by name."""
    count = len(next(iter(parameters.values())))
    return [
        {
            "trial": i + 1,
            "cost": float(count - i),
            "parameters": {k: {"value": v[i]} for k, v in parameters.items() if v[i] is not None},
        }
        for i in range(count)
    ]


def test_a_session_pair_needs_two_trial_columns_with_a_trial_that_holds_both(tmp_path):
    bounds = {
        **K_BOUNDS,
        "Sy": ParameterBound(lower=0.01, upper=0.3, search_space="log", units="-"),
    }
    apart = journal_session(
        tmp_path / "a", trial_rows({"K": [1e-5, 2e-5, None, None], "Sy": [None, None, 0.1, 0.2]}),
        bounds=bounds, best_trial=1,
    )  # fmt: skip
    with pytest.raises(FigureNotApplicable, match="No trial has both"):
        data(apart, variable=["trials.K", "trials.Sy"])
    with pytest.raises(FigureNotApplicable, match="needs two trials"):
        data(apart, variable=["trials.K"])
    together = journal_session(
        tmp_path / "b", trial_rows({"K": [1e-5, 2e-5, 4e-5], "Sy": [0.05, 0.1, 0.2]}),
        bounds=bounds, best_trial=1,
    )  # fmt: skip
    out = data(together, variable=["trials.K", "trials.cost"], reference=["one_to_one", "zero"])
    assert out.table["key"].tolist() == [1, 2, 3] and out.trials == (3, 3)
    assert out.one_to_one and out.references == ((0.0, "zero"),)


def test_the_scoring_window_is_the_one_the_metrics_carry_else_none():
    one = pd.DataFrame({"window_start": ["2001-01-01"] * 2, "window_end": ["2001-12-31"] * 2})
    two = one.assign(window_end=["2001-12-31", "2002-12-31"])
    assert xy._window(one) == (pd.Timestamp("2001-01-01"), pd.Timestamp("2001-12-31"))
    assert xy._window(two) is None and xy._window(None) is None and xy._window(one[[]]) is None


def test_two_series_on_other_periods_and_two_fields_on_other_cells_are_refused(
    stored_run, monkeypatch
):
    days = pd.date_range("2001-01-01", periods=4, freq="D")
    monkeypatch.setattr(xy, "read_series", lambda run, name, **kw: pd.Series(np.ones(4 if name == "discharge" else 3), index=days[: 4 if name == "discharge" else 3]))  # fmt: skip
    with pytest.raises(FigureNotApplicable, match="not on the same periods"):
        data(stored_run, variable=["discharge", "rainfall"], station=GAUGE)
    monkeypatch.setattr(xy, "read_field", lambda run, name, **kw: np.ones((12,) if name == "recharge" else (2, 12)))  # fmt: skip
    with pytest.raises(FigureNotApplicable, match="do not share their cells"):
        data(stored_run, variable=["recharge", "drain"], station=ZONE)


def test_references_a_log_axis_cannot_show_are_skipped_and_the_scores_sit_inside_a_square_plot(
    stored_run,
):
    out = data(stored_run, variable=["rainfall", "discharge"], station=GAUGE, scale="log", reference=["zero", "one_to_one"])  # fmt: skip
    ax = static.new_figure(THEME).axes[0]
    xy.draw(ax, out, THEME)
    assert len(ax.lines) == 1 and ax.lines[0].get_label() == "1:1"  # no zero line on log y
    low, high = out.table[["x", "y"]].to_numpy().min(), out.table[["x", "y"]].to_numpy().max()
    assert ax.get_xlim() == pytest.approx((low / 1.15, high * 1.15))
    many = data(stored_run, variable=["discharge"], station=GAUGE, observed=True, reference=["one_to_one"], scores=True)  # fmt: skip
    wide = dataclasses.replace(many, scores=many.scores.assign(metric="kge"))
    ax = static.new_figure(THEME).axes[0]
    xy.draw(ax, wide, THEME)
    assert ax.get_title(loc="right") == "" and ax.texts[0].get_text().startswith("KGE")
    silent = dataclasses.replace(many, scores=many.scores.assign(metric="bias"))
    ax = static.new_figure(THEME).axes[0]
    xy.draw(ax, silent, THEME)
    assert not ax.texts
