"""The map frame on the small stored run: the numbers of ``data`` and what ``draw`` puts on the axes."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import LogNorm, TwoSlopeNorm

from hydromodpy.display import static
from hydromodpy.display.frames import map as frame
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from tests.unit.display._stored_run import HEAD_TOP, N_CELLS

THEME = THEMES["default"]


def data(run, **panel):
    return frame.data(run, PanelRequest(**panel))


def drawn(out):
    fig = static.new_figure(THEME)
    frame.draw(fig.axes[0], out, THEME)
    return fig, fig.axes[0]


REDUCED = [
    ({"reduce": "mean"}, HEAD_TOP - 1.0 + 1.5),
    ({"reduce": "max"}, HEAD_TOP + 2.0),
    ({"change": (0, 3)}, np.full(N_CELLS, 3.0)),
    ({"time": 1}, HEAD_TOP),
]


@pytest.mark.parametrize(("fields", "expected"), REDUCED)
def test_time_operations_on_a_head(stored_run, fields, expected):
    out = data(stored_run, variable="head", **fields)
    np.testing.assert_allclose(out.table["value"], expected)
    assert list(out.table.columns) == list(frame.MAP_COLUMNS)


def test_frequency_counts_the_periods_with_a_value(stored_run):
    out = data(stored_run, variable="recharge", reduce="frequency")
    np.testing.assert_allclose(out.table["value"], 1.0)
    assert out.scale == "sequential" and out.label.startswith("Share of")


def test_a_difference_is_signed_and_has_no_isolines(stored_run):
    out = data(stored_run, variable="head", change=(0, 3))
    assert out.scale == "diverging" and not out.contours
    assert out.label.startswith("Change in hydraulic head (")
    _, ax = drawn(out)
    norm = ax.collections[0].norm
    assert isinstance(norm, TwoSlopeNorm) and norm.vcenter == 0


def test_a_one_signed_flow_takes_a_sequential_ramp_and_shows_the_sign_rule(stored_run):
    out = data(stored_run, variable="recharge")
    assert out.scale == "sequential" and out.ramp != THEME.ramps["diverging"]
    _, ax = drawn(out)
    assert "enters the aquifer" in ax.get_title(loc="right")


def test_a_categorical_keeps_its_classes_in_a_legend(stored_run):
    out = data(stored_run, variable="seepage_mask")
    assert out.classes == ((0, "no seepage"), (1, "seepage")) and out.ramp == ""
    fig, ax = drawn(out)
    assert len(fig.axes) == 1
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["no seepage", "seepage"]


def test_a_state_is_drawn_once_in_kilometres_with_isolines_and_a_colour_bar(stored_run):
    fig, ax = drawn(data(stored_run, variable="head"))
    assert len([c for c in ax.collections if isinstance(c, PolyCollection)]) == 1
    assert len(ax.collections) > 1 and len(fig.axes) == 2
    assert ax.get_aspect() == 1.0 and ax.get_xlabel().endswith(", km)")


def test_a_log_scale_and_shared_limits(stored_run):
    out = data(stored_run, variable="head", scale="log")
    assert out.log
    assert isinstance(drawn(out)[1].collections[0].norm, LogNorm)
    shared = dataclasses.replace(out, limits=(50.0, 500.0))
    assert drawn(shared)[1].collections[0].norm.vmax == 500.0


def test_the_box_keeps_the_cells_inside(stored_run):
    out = data(stored_run, variable="head", bbox=(385000.0, 6814000.0, 385900.0, 6814900.0))
    assert out.table["cell"].tolist() == [0, 1, 4, 5]


def test_a_reach_column_is_drawn_as_lines_to_the_downstream_cell(stored_run):
    out = data(stored_run, type="map", variable="sfr_reaches.rgrd")
    assert list(out.table.columns) == list(frame.REACH_COLUMNS)
    np.testing.assert_allclose(out.table["value"], [0.01, 0.02, 0.03])
    assert np.isnan(out.table["x_down"].iloc[-1]) and out.table["x_down"].iloc[0] == 385750.0
    _, ax = drawn(out)
    assert any(isinstance(c, LineCollection) for c in ax.collections)


def test_another_run_and_a_missing_column_are_refused(stored_run):
    with pytest.raises(FigureNotApplicable, match="panel operations of a later"):
        data(stored_run, variable="head", against="other")
    with pytest.raises(FigureNotApplicable, match="no column 'slope'"):
        data(stored_run, type="map", variable="sfr_reaches.slope")
