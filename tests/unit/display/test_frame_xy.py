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
from tests._helpers.run_builders import GAUGE

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
