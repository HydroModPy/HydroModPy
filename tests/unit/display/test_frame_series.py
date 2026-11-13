"""The series frame on the small stored run: the numbers of ``data`` and what ``draw`` puts on the axes."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display import static
from hydromodpy.display.frames import series
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from tests._helpers.run_builders import GAUGE
from tests.unit.display._stored_run import STEP

THEME = THEMES["default"]
ZONE = "zone:catchment"
DAYS = np.array([31, 28, 31, 30]) * 86400.0
ZONE_AREA = 8 * STEP**2


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
    text = series._score_text(out.scores, many=False)
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
    ({"variable": "discharge", "station": GAUGE, "reduce": "mean"}, "reduce and change"),
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
