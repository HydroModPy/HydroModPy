"""The three special calibration figures draw the trials a session holds, with numbers."""

from __future__ import annotations

import pytest

from hydromodpy.display import static
from hydromodpy.display.special import calibration_landscape, calibration_progress, root_search
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import get_theme
from hydromodpy.results.session.descriptor import ParameterBound

from ._calibration_journal import (
    K_BOUNDS,
    TWO_ROOTS,
    journal_session,
    steady_bisection_rows,
    two_root_rows,
)

THEME = get_theme("default")
BOUNDS = {**K_BOUNDS, "Sy": ParameterBound(lower=0.01, upper=0.3, search_space="log", units="-")}
COSTS = [4.0, 1.0, 2.0, 3.0]  # trial 2 is the lowest, the session returns trial 3


def ax_of():
    fig = static.new_figure(THEME)
    return fig, fig.axes[0]


def labelled(ax, label):
    return next(a for a in ax.lines + ax.collections if a.get_label() == label)


def rows(params, costs=COSTS):
    return [
        {"trial": i + 1, "cost": c, "parameters": {k: {"value": v[i]} for k, v in params.items()}}
        for i, c in enumerate(costs)
    ]


def two_parameters(tmp_path, *, only_k=()):
    k, sy = [1e-5, 2e-5, 4e-5, 8e-5], [0.05, 0.1, 0.12, 0.2]
    table = rows({"K": k, "Sy": sy})
    for number in only_k:  # trials that searched K alone
        table[number]["parameters"].pop("Sy")
    return journal_session(tmp_path, table, bounds=BOUNDS, best_trial=3)


def test_progress_star_at_returned_trial_and_margin_threshold(tmp_path):
    session = journal_session(
        tmp_path, rows({"K": [1e-5, 2e-5, 4e-5, 8e-5]}), bounds=K_BOUNDS, best_trial=3
    )
    _, ax = ax_of()
    calibration_progress.draw(session, ax, THEME)
    assert labelled(ax, "Returned trial").get_offsets().tolist() == [[3.0, 2.0]]
    assert labelled(ax, "Acceptable cost 2.3").get_ydata()[0] == pytest.approx(1.15 * 2.0)
    assert labelled(ax, "Best so far").get_ydata().tolist() == [4.0, 1.0, 1.0, 1.0]
    assert len(labelled(ax, "Trial").get_offsets()) == 4


def noted(ax, word):
    return next(t.get_text() for t in ax.texts if word in t.get_text())


def test_a_returned_trial_that_is_not_drawn_gets_no_star_and_a_note(tmp_path):
    session = journal_session(tmp_path, rows({"K": [1e-5, 2e-5, 4e-5, 8e-5]}), bounds=K_BOUNDS,
                              best_trial=9)  # fmt: skip
    _, ax = ax_of()
    calibration_progress.draw(session, ax, THEME)
    assert "Returned trial" not in ax.get_legend_handles_labels()[1]
    assert "not among the trials drawn" in noted(ax, "returned")
    assert not [a for a in ax.lines if a.get_label().startswith("Acceptable")]  # no cost to scale


def test_the_landscape_draws_the_phase_that_searched_two_parameters_alone(tmp_path):
    table = rows(
        {"K": [1e-5, 2e-5, 4e-5, 8e-5], "Sy": [0.05, 0.1, 0.12, 0.2]}, [9.0, 8.0, 4.0, 2.0]
    )
    table[0]["parameters"].pop("Sy")
    table[1]["parameters"].pop("Sy")
    for i, row in enumerate(table):
        row["phase"] = "first" if i < 2 else "second"
    session = journal_session(tmp_path, table, bounds=BOUNDS, phases=["first", "second"],
                              phase_best={"first": 2, "second": 3}, best_trial=3)  # fmt: skip
    _, ax = ax_of()
    calibration_landscape.draw(session, ax, THEME)
    assert ax.collections[0].get_array().tolist() == [4.0, 2.0]  # the costs of phase two only
    assert labelled(ax, "Cost under 4.6").get_offsets().tolist() == [[4e-5, 0.12], [8e-5, 0.2]]


def test_progress_staged_session_has_one_panel_per_phase(tmp_path):
    table = rows({"K": [1e-5, 2e-5, 4e-5, 8e-5]})
    for i, row in enumerate(table):
        row["phase"] = "first" if i < 3 else "second"
    session = journal_session(tmp_path, table, bounds=K_BOUNDS, phases=["first", "second"],
                              phase_best={"first": 2, "second": 4}, best_trial=4)  # fmt: skip
    _, ax = ax_of()
    calibration_progress.draw(session, ax, THEME)
    panels = ax.child_axes
    assert len(panels) == 2
    assert [p.get_title() for p in panels] == ["first", "second"]
    assert labelled(panels[0], "Returned trial").get_offsets().tolist() == [[2.0, 1.0]]


def test_landscape_counts_trials_that_searched_the_pair(tmp_path):
    _, ax = ax_of()
    calibration_landscape.draw(two_parameters(tmp_path, only_k=(0,)), ax, THEME)
    assert len(ax.collections[0].get_offsets()) == 3
    assert labelled(ax, "Returned trial").get_offsets().tolist() == [[4e-5, 0.12]]
    ring = labelled(ax, "Cost under 2.3")  # 1.15 times the returned cost, trials 2 and 3 are under
    assert ring.get_offsets().tolist() == [[2e-5, 0.1], [4e-5, 0.12]]
    assert ax.get_xscale() == ax.get_yscale() == "log"


def test_landscape_draws_three_parameters_as_insets(tmp_path):
    k, sy, ru = [1e-5, 2e-5, 4e-5, 8e-5], [0.05, 0.1, 0.12, 0.2], [60.0, 80.0, 90.0, 100.0]
    bounds = {**BOUNDS, "ru": ParameterBound(lower=50.0, upper=250.0, search_space="identity")}
    session = journal_session(tmp_path, rows({"K": k, "Sy": sy, "ru": ru}), bounds=bounds,
                              best_trial=3)  # fmt: skip
    _, ax = ax_of()
    calibration_landscape.draw(session, ax, THEME)
    assert len(ax.child_axes) == 3


def test_root_search_shades_the_last_bracket(tmp_path):
    session = journal_session(tmp_path, steady_bisection_rows(), bounds=K_BOUNDS, best_trial=15)
    _, ax = ax_of()
    root_search.draw(session, ax, THEME)
    span = next(p for p in ax.patches if p.get_label() == "Final bracket")
    assert span.get_x() == pytest.approx(8.0584e-5)
    assert span.get_x() + span.get_width() == pytest.approx(8.1069e-5)
    assert len(labelled(ax, "Simulated to observed").get_xdata()) == 15
    assert "K* = 8.107e-05, bracket [8.058e-05, 8.107e-05], a factor 1.006" in noted(ax, "bracket")


def test_root_search_of_two_bounds_draws_one_signed_gap_and_bracket_per_bound(tmp_path):
    session = journal_session(tmp_path, two_root_rows(), bounds=K_BOUNDS, best_trial=24,
                              root_search=TWO_ROOTS)  # fmt: skip
    _, ax = ax_of()
    root_search.draw(session, ax, THEME)
    low = labelled(ax, "Signed gap, minimal bound").get_ydata()
    assert (len(low), low.min(), low.max()) == (24, -2387.8, 375.4)
    spans = {p.get_label(): p for p in ax.patches if p.get_label().startswith("Final")}
    high = spans["Final bracket, maximal bound"]
    assert high.get_x() == pytest.approx(1.358e-6) and high.get_width() == pytest.approx(8e-9, rel=0.02)  # fmt: skip
    lines = noted(ax, "bracket").split("\n")
    assert [line.split(" = ")[0] for line in lines[:2]] == ["minimal: K*_minimal", "maximal: K*_maximal"]  # fmt: skip
    assert len(spans) == 2 and len(labelled(ax, "Cost under 213").get_offsets()) == 2 * 21


@pytest.mark.parametrize("module", [root_search, calibration_landscape, calibration_progress])
def test_refuses_a_session_without_its_data(tmp_path, module):
    """One parameter and no root search: only the progress figure can draw it."""
    session = journal_session(
        tmp_path, rows({"K": [1e-5, 2e-5, 4e-5, 8e-5]}), bounds=K_BOUNDS, best_trial=3
    )
    _, ax = ax_of()
    if module is calibration_progress:
        module.draw(session, ax, THEME)
    else:
        with pytest.raises(FigureNotApplicable):
            module.draw(session, ax, THEME)
