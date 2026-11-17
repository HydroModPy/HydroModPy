"""The series frame on the small stored run: the numbers of ``data`` and what ``draw`` puts on the axes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import static
from hydromodpy.display.frames import series
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from tests._helpers.run_builders import GAUGE
from tests.unit.display._calibration_journal import K_BOUNDS, journal_session
from tests.unit.display._stored_run import ZONE_AREA

THEME = THEMES["default"]
ZONE = "zone:catchment"
DAYS = np.array([31, 28, 31, 30]) * 86400.0


def data(run, **panel):
    return series.data(run, PanelRequest(type="series", **panel))


def drawn(run, **panel):
    ax = static.new_figure(THEME).axes[0]
    series.draw(ax, data(run, **panel), THEME)
    return ax


def test_a_discharge_keeps_its_stored_numbers_and_shows_its_unit(stored_run):
    out = data(stored_run, variable="discharge", station=GAUGE)
    np.testing.assert_allclose(out.table["simulated"], [1.0, 2.0, 3.0, 2.5])
    assert "discharge (" in out.label


def test_a_cell_flow_over_a_zone_is_divided_by_the_zone_area(stored_run):
    out = data(stored_run, variable="recharge", station=ZONE)
    expected = 8 * 2.0e-3 * (1 + 0.1 * np.arange(4)) / ZONE_AREA * 86400 * 1000
    np.testing.assert_allclose(out.table["simulated"], expected, rtol=1e-4)


def test_a_cumulative_uses_the_real_length_of_each_month(stored_run):
    out = data(stored_run, variable="recharge", station=ZONE, cumulative=True)
    rate = 8 * 2.0e-3 * (1 + 0.1 * np.arange(4))
    np.testing.assert_allclose(
        out.table["simulated"], np.cumsum(rate * DAYS) / ZONE_AREA, rtol=1e-4
    )
    assert out.label.startswith("Cumulative recharge (")
    volume = data(stored_run, variable="discharge", station=GAUGE, cumulative=True)
    np.testing.assert_allclose(volume.table["simulated"], np.cumsum([1.0, 2.0, 3.0, 2.5] * DAYS))


def test_the_observed_record_is_a_column_and_against_is_the_difference(stored_run):
    both = data(stored_run, variable="discharge", station=GAUGE, observed=True)
    np.testing.assert_allclose(both.table["observed"].dropna(), [1.1, 2.2, 3.3])
    gap = data(stored_run, variable="discharge", station=GAUGE, against="observed")
    assert gap.residual and "observed" not in gap.table
    np.testing.assert_allclose(gap.table["simulated"].dropna(), [0.9, 0.8, -0.8])
    assert gap.label.startswith("Residual, simulated minus observed (")


def test_the_scores_come_from_the_metrics_with_their_window(stored_run):
    out = data(stored_run, variable="discharge", station=GAUGE, scores=True)
    text = series.score_text(out.scores, many=False)
    assert text.startswith("NSE 0.80") and "scored 2020-01 to 2020-12" in text


def test_the_budget_is_the_kept_terms_over_a_zone(stored_run):
    out = data(stored_run, variable="budget", station=ZONE)
    assert list(out.table["variable"].unique()) == ["recharge", "drain"]
    np.testing.assert_allclose(
        out.table.groupby("variable")["simulated"].first()["drain"],
        -0.5 * out.table["simulated"].iloc[0],
        rtol=1e-4,
    )


REFUSED = [
    ({"variable": "head", "station": ZONE, "cumulative": True}, "cannot be cumulated"),
    ({"variable": "discharge", "station": GAUGE, "reduce": "mean"}, "does not take 'reduce'"),
    ({"variable": "discharge", "station": GAUGE, "against": "other"}, "against 'observed'"),
    ({"variable": "discharge", "station": "catchment", "against": "observed"}, "no observation"),
]


@pytest.mark.parametrize(("fields", "words"), REFUSED)
def test_what_a_series_cannot_do_is_refused(stored_run, fields, words):
    with pytest.raises(FigureNotApplicable, match=words):
        data(stored_run, **fields)


def test_lines_points_scores_and_a_window(stored_run):
    ax = drawn(
        stored_run, variable="discharge", station=GAUGE, observed=True, scores=True,
        time=[1, 2],
    )  # fmt: skip
    simulated, observed = ax.lines[:2]
    assert simulated.get_color() == THEME.roles["simulated"] and len(observed.get_xdata()) == 2
    assert "NSE 0.80" in ax.get_title(loc="right") and ax.get_legend() is not None
    assert len(ax.patches) == 1


def test_a_log_axis_with_references_and_a_residual_zero_line(stored_run):
    ref = [{"value": 2.0, "label": "limit"}, "zero"]
    ax = drawn(stored_run, variable="discharge", station=GAUGE, scale="log", reference=ref)
    assert ax.get_yscale() == "log" and len(ax.lines) == 3
    gap = drawn(stored_run, variable="discharge", station=GAUGE, against="observed")
    assert gap.get_legend().get_texts()[0].get_text() == "simulated minus observed"


def test_a_stack_puts_inflows_above_zero_with_distinct_colours_and_registry_labels(stored_run):
    ax = drawn(stored_run, variable="budget", station=ZONE, stack=True)
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert labels == ["Recharge", "Drain flow"]
    assert len({tuple(bar.get_facecolor()) for bar in ax.patches}) == 2
    assert all(bar.get_height() >= 0 for bar in ax.patches[:4])


@pytest.mark.parametrize(
    ("fields", "words"),
    [
        (
            {"variable": "discharge", "station": GAUGE, "reference": ["one_to_one"]},
            "does not apply to a series",
        ),
        ({"station": GAUGE}, "needs a variable"),
    ],
)
def test_a_reference_that_is_no_value_and_a_missing_variable_are_refused(stored_run, fields, words):
    with pytest.raises(FigureNotApplicable, match=words):
        data(stored_run, **fields)


def test_a_session_series_draws_a_trial_column_and_refuses_anything_else(tmp_path):
    rows = [{"trial": i + 1, "cost": c, "parameters": {"K": {"value": k}}}
            for i, (c, k) in enumerate(zip([4.0, 1.0, 2.0], [1e-5, 2e-5, 4e-5], strict=True))]  # fmt: skip
    session = journal_session(tmp_path, rows, bounds=K_BOUNDS, best_trial=2)
    ax = static.new_figure(THEME).axes[0]
    series.draw(ax, series.data(session, PanelRequest(type="series", variable=["trials.K"])), THEME)
    assert ax.lines[0].get_xdata().tolist() == [1, 2, 3] and ax.get_xlabel() == "Trial"
    assert ax.get_legend() is None  # one line needs no legend
    for fields, words in (
        ({"variable": ["head"]}, "takes trials"),
        ({"variable": ["trials.K"], "observed": True}, "no such axis"),
    ):
        with pytest.raises(FigureNotApplicable, match=words):
            series.data(session, PanelRequest(type="series", **fields))


def test_two_stations_are_told_apart_in_the_legend(stored_run):
    ax = drawn(stored_run, variable="discharge", station=[GAUGE, "catchment"])
    texts = [t.get_text() for t in ax.get_legend().get_texts()]
    assert texts[0].endswith(f"({GAUGE})") and texts[1].endswith("(catchment)")


def scored(**columns):
    base = {"variable": "q", "station": "s", "metric": "nse", "value": 0.5}
    return pd.DataFrame([{**base, **columns}])


@pytest.mark.parametrize(
    ("table", "text"),
    [
        (scored(), "NSE 0.50"),
        (
            scored(window_start="2001-01-01", window_end="2001-12-31"),
            "NSE 0.50   (scored 2001-01 to 2001-12)",
        ),
        (
            pd.concat(
                [
                    scored(window_start="2001-01-01", window_end="2001-12-31"),
                    scored(window_start="2002-01-01", window_end="2002-12-31", metric="kge"),
                ]
            ),
            "KGE 0.50   NSE 0.50",
        ),  # fmt: skip
        (scored(value=np.nan), ""),
        (scored(metric="bias"), ""),
    ],
)
def test_the_score_line_names_a_single_window_only_and_skips_a_missing_value(table, text):
    assert series.score_text(table, many=False) == text


def test_the_stacked_bars_of_a_numbered_axis_keep_their_numbers():
    rows = pd.DataFrame({"time": [1, 2, 3], "simulated": [1.0, -2.0, 3.0]})
    ax = static.new_figure(THEME).axes[0]
    series._stacked(ax, [("recharge", None, rows)], False, THEME)
    assert [p.get_x() for p in ax.patches[:3]] == [1, 2, 3]


def test_a_long_record_is_a_thin_line_and_a_short_one_is_dots():
    ax = static.new_figure(THEME).axes[0]
    for count in (series.OBSERVED_LINE_FROM + 1, 5):
        series.draw_observed(ax, np.arange(count), np.arange(count), THEME)
    long, short = ax.lines
    assert long.get_linestyle() == "-" and short.get_linestyle() == "None" and short.get_marker() == "o"  # fmt: skip


def test_a_panel_without_a_finite_score_has_no_title(stored_run):
    out = data(stored_run, variable="discharge", station=GAUGE, scores=True)
    out = replace_scores(out, out.scores.assign(value=np.nan))
    ax = static.new_figure(THEME).axes[0]
    series.draw(ax, out, THEME)
    assert ax.get_title(loc="right") == ""


def replace_scores(out, scores):
    import dataclasses

    return dataclasses.replace(out, scores=scores)


def test_the_interactive_series_carries_the_zero_line_the_references_and_the_scores(stored_run):
    pytest.importorskip("plotly")
    out = data(stored_run, variable="discharge", station=GAUGE, against="observed",
               reference=["zero", {"value": 0.5, "label": "limit"}], scores=True)  # fmt: skip
    traces, axes = series.draw_interactive(out, THEME)
    flat = [t for t in traces if t.hoverinfo == "skip"]
    assert [(t.name, t.showlegend) for t in flat] == [
        (None, False),
        ("zero", False),
        ("limit", True),
    ]
    assert axes["title"] == "NSE 0.80"
