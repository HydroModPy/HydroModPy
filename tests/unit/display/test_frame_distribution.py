"""The distribution frame on the small stored run: weights, bins, exceedance and what ``draw`` adds."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display import static, variables
from hydromodpy.display.frames import distribution
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from hydromodpy.results.session.descriptor import ParameterBound
from tests._helpers.run_builders import GAUGE
from tests.unit.display._calibration_journal import K_BOUNDS, journal_session
from tests.unit.display._stored_run import AREAS, ZONE_AREA

THEME = THEMES["default"]
DAYS = np.array([31, 28, 31, 30]) * 86400.0


def data(run, **panel):
    return distribution.data(run, PanelRequest(type="distribution", **panel))


def test_a_field_histogram_weights_sum_to_one_over_the_zone(stored_run):
    out = data(stored_run, variable="topography")
    assert tuple(out.table.columns) == distribution.HISTOGRAM_COLUMNS
    assert out.weight == "area" and out.table["share"].sum() == pytest.approx(1.0)
    assert out.table["low"].iloc[0] == pytest.approx(108.0)
    assert out.table["high"].iloc[-1] == pytest.approx(115.0)
    # Cell 7 is a wide cell and holds the highest topography of the zone.
    top = data(stored_run, variable="topography", cumulative=True)
    assert top.table["exceedance"].iloc[0] == pytest.approx(AREAS[7] / ZONE_AREA)


def test_a_series_histogram_is_weighted_by_period_length(stored_run):
    out = data(stored_run, variable="discharge", station=GAUGE)
    assert out.weight == "time" and out.table["share"].sum() == pytest.approx(1.0)
    first = out.table.iloc[0]
    expected = DAYS[(np.array([1.0, 2.0, 3.0, 2.5]) < first["high"])].sum() / DAYS.sum()
    assert first["share"] == pytest.approx(expected)


def test_the_exceedance_curve_decreases_and_gives_the_weighted_median(stored_run):
    out = data(stored_run, variable="discharge", station=GAUGE, cumulative=True, scale="linear")
    assert tuple(out.table.columns) == distribution.EXCEEDANCE_COLUMNS
    value, share = out.table["value"].to_numpy(), out.table["exceedance"].to_numpy()
    assert value[0] == 3.0 and np.all(np.diff(value) <= 0) and np.all(np.diff(share) >= 0)
    assert share[0] == pytest.approx(DAYS[2] / DAYS.sum()) and share[-1] == pytest.approx(1.0)
    assert value[np.searchsorted(share, 0.5)] == 2.5  # 31 d at 3, then 30 d at 2.5


def test_observed_gives_two_sources_and_against_gives_the_residuals(stored_run):
    both = data(stored_run, variable="discharge", station=GAUGE, observed=True, cumulative=True)
    assert set(both.table["source"]) == {"simulated", "observed"}
    gap = data(stored_run, variable="discharge", station=GAUGE, against="observed", scale="linear")
    assert gap.residual and set(gap.table["source"]) == {"simulated"}
    assert gap.table["low"].iloc[0] == pytest.approx(-0.8) and gap.table["high"].iloc[
        -1
    ] == pytest.approx(0.9)


@pytest.mark.parametrize(
    ("panel", "word"),
    [
        ({"by": "month"}, "does not take 'by'"),
        ({"stack": True}, "stack"),
        ({"against": "observed"}, "no observed field"),
        ({"variable": "seepage_mask"}, "categorical"),
        ({"variable": ["head", "recharge"]}, "one variable"),
    ],
)
def test_what_a_distribution_cannot_draw_is_refused(stored_run, panel, word):
    panel = {"variable": "head", **panel}
    with pytest.raises(FigureNotApplicable, match=word):
        data(stored_run, **panel)


def drawn(run, **panel):
    ax = static.new_figure(THEME).axes[0]
    distribution.draw(ax, data(run, **panel), THEME)
    return ax


@pytest.mark.parametrize(
    ("panel", "log", "lines"),
    [
        ({"observed": True, "scale": "log"}, True, 2),
        ({"against": "observed", "scale": "log"}, True, 1),
        ({"against": "observed", "scale": "linear"}, False, 1),
    ],
)
def test_an_exceedance_curve_puts_the_values_on_y_and_a_zero_line_on_a_residual(
    stored_run, panel, log, lines
):
    ax = drawn(stored_run, variable="discharge", station=GAUGE, cumulative=True, **panel)
    assert ax.get_xlim() == (0, 100) and (ax.get_yscale() == "log") == log
    residual = "against" in panel
    assert len(ax.lines) == lines + residual  # the curves, and the zero line of a residual
    assert (ax.get_legend() is not None) == (lines == 2)
    assert ax.get_ylabel().startswith("Residual") == residual


def test_a_categorical_variable_reduced_to_a_frequency_is_a_share_of_steps(stored_run):
    out = data(stored_run, variable="seepage_mask", reduce="frequency")
    assert out.label == variables.FREQUENCY_LABEL


def test_a_station_without_a_record_draws_the_simulation_alone_unless_against_asks(stored_run):
    out = data(stored_run, variable="discharge", station="catchment", observed=True)
    assert set(out.table["source"]) == {"simulated"}
    with pytest.raises(FigureNotApplicable, match="no observation"):
        data(stored_run, variable="discharge", station="catchment", against="observed")


def test_a_log_axis_with_no_value_above_zero_is_refused(stored_run):
    with pytest.raises(FigureNotApplicable, match="no value above zero"):
        data(stored_run, variable="drain", scale="log")


def test_a_session_distribution_takes_a_trial_column_and_no_other_axis(tmp_path):
    rows = [
        {"trial": i + 1, "cost": c, "parameters": {"K": {"value": k}}}
        for i, (c, k) in enumerate(zip([4.0, 1.0, 2.0, 3.0], [1e-5, 2e-5, 4e-5, 8e-5], strict=True))
    ]
    session = journal_session(tmp_path, rows, bounds=K_BOUNDS, best_trial=2)
    out = data(session, variable="trials.K")
    assert out.weight == "trials" and out.log and out.trials == (4, 4)
    assert out.table["share"].sum() == pytest.approx(1.0)
    with pytest.raises(FigureNotApplicable, match="takes a trials"):
        data(session, variable="head")
    with pytest.raises(FigureNotApplicable, match="no such axis"):
        data(session, variable="trials.K", time=0)


def test_a_distribution_against_anything_but_the_record_is_refused(stored_run):
    request = PanelRequest.model_construct(type="distribution", variable=["head"], against="x")
    with pytest.raises(FigureNotApplicable, match="only be drawn against"):
        distribution.data(stored_run, request)
