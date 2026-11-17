"""The map frame on the small stored run: the numbers of ``data`` and what ``draw`` puts on the axes."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import LogNorm, TwoSlopeNorm

from hydromodpy.display import static
from hydromodpy.display.frames import map as frame
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import Compared, FigureNotApplicable
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
    assert out.scale == "sequential" and out.label.endswith(", share of the periods")
    assert out.blank_zero and out.caption == "" and frame._ramp(out, THEME) == "share"


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
    # Class 0 is the absence: its cells are left undrawn and it has no legend entry.
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["seepage"]


def test_a_state_is_drawn_once_with_its_title_its_period_isolines_and_a_colour_bar(stored_run):
    out = data(stored_run, variable="head")
    fig, ax = drawn(out)
    assert len([c for c in ax.collections if isinstance(c, PolyCollection)]) == 1
    assert len(ax.collections) > 1 and len(fig.axes) == 2
    assert ax.get_aspect() == 1.0 and len(ax.get_xticks()) == 0 and ax.get_xlabel() == ""
    assert (ax.get_title(loc="left"), ax.get_title(loc="right")) == (out.label, "April 2001")
    assert fig.axes[1].get_ylabel() == ""  # the title carries the unit
    assert data(stored_run, variable="topography").caption == ""


def test_a_log_scale_and_shared_limits(stored_run):
    out = data(stored_run, variable="head", scale="log")
    assert out.log
    assert isinstance(drawn(out)[1].collections[0].norm, LogNorm)
    shared = dataclasses.replace(out, limits=(50.0, 500.0))
    assert drawn(shared)[1].collections[0].norm.vmax == 500.0


def test_limits_point_the_colour_bar_and_a_line_is_drawn_dashed(stored_run):
    trace = [(385000.0, 6814000.0), (385900.0, 6814900.0)]
    out = data(stored_run, variable="head", limits=(0.0, 1.0), line=trace)
    fig, ax = drawn(out)
    cells = ax.collections[0]
    assert (cells.norm.vmin, cells.norm.vmax, cells.colorbar.extend) == (0.0, 1.0, "max")
    (line,) = ax.lines
    assert line.get_linestyle() == "--" and list(zip(*line.get_data(), strict=True)) == trace
    assert drawn(data(stored_run, variable="head"))[1].collections[0].colorbar.extend == "neither"


def test_the_box_keeps_the_cells_inside(stored_run):
    out = data(stored_run, variable="head", bbox=(385000.0, 6814000.0, 385900.0, 6814900.0))
    assert out.table["cell"].tolist() == [0, 1, 4, 5]


def test_a_reach_column_is_drawn_as_lines_to_the_downstream_cell(stored_run):
    out = data(stored_run, type="map", variable="sfr_reaches.strahler")
    assert list(out.table.columns) == list(frame.REACH_COLUMNS)
    assert out.label == "Strahler order" and out.classes == ((1, "1"),)
    np.testing.assert_allclose(out.table["value"], [1, 1, 1])
    assert np.isnan(out.table["x_down"].iloc[-1]) and out.table["x_down"].iloc[0] == 385750.0
    _, ax = drawn(out)
    assert any(isinstance(c, LineCollection) for c in ax.collections)


def test_another_run_and_a_missing_column_are_refused(stored_run):
    with pytest.raises(FigureNotApplicable, match="resolved"):
        data(stored_run, variable="head", against="other")
    with pytest.raises(FigureNotApplicable, match="no row in COLUMN_REGISTRY"):
        data(stored_run, type="map", variable="sfr_reaches.slope")


class WithTable:
    """A run whose ``table`` is replaced, every other read going to the run."""

    def __init__(self, run, tables):
        self._run, self._tables = run, tables

    def table(self, name):
        return self._tables[name] if name in self._tables else self._run.table(name)

    def __getattr__(self, name):
        return getattr(self._run, name)


def test_a_reach_without_a_cell_is_left_out_and_a_column_the_table_lacks_is_refused(stored_run):
    reaches = stored_run.table("sfr_reaches").copy()
    reaches.loc[1, "cell2d"] = np.nan
    out = data(WithTable(stored_run, {"sfr_reaches": reaches}), variable="sfr_reaches.strahler")
    assert len(out.table) == 2
    bare = WithTable(stored_run, {"sfr_reaches": reaches.drop(columns="strahler")})
    with pytest.raises(FigureNotApplicable, match="has no column 'strahler'"):
        data(bare, variable="sfr_reaches.strahler")


@pytest.mark.parametrize(
    ("panel", "word"),
    [
        ({"variable": "seepage_mask"}, "two runs are subtracted through reduce"),
        ({"variable": "sfr_reaches.strahler"}, "cannot be subtracted between runs"),
    ],
)
def test_a_difference_of_two_runs_refuses_what_cannot_be_subtracted(stored_run, panel, word):
    with pytest.raises(FigureNotApplicable, match=word):
        frame.data(Compared(stored_run, stored_run), PanelRequest(**panel))


def test_a_time_window_and_a_change_with_a_time_are_refused_on_a_map(stored_run):
    with pytest.raises(FigureNotApplicable, match="change replaces time and reduce"):
        data(stored_run, variable="head", change=(0, 3), time=1)
    with pytest.raises(FigureNotApplicable, match="not over a window"):
        data(stored_run, variable="head", time=[0, 2])


def test_a_crs_has_a_short_name_and_none_or_a_bad_one_is_the_mesh_crs():
    assert frame.crs_name(None) == "mesh CRS" and frame.crs_name("not a crs") == "mesh CRS"
    assert frame.crs_name("EPSG:2154") == "Lambert-93"


def test_a_field_without_any_spread_draws_without_isolines(stored_run):
    out = data(stored_run, variable="head", contours=True)
    flat = dataclasses.replace(out, table=out.table.assign(value=1.0))
    _, ax = drawn(flat)
    assert len(ax.collections) == 1  # the cells only, no contour set


def test_a_categorical_map_has_no_ramp(stored_run):
    out = data(stored_run, variable="seepage_mask")
    assert frame._ramp(out, THEME) == ""


@pytest.mark.parametrize(
    ("panel", "kind"),
    [
        ({"variable": "seepage_mask"}, "classes"),
        ({"variable": "head", "scale": "log"}, "log"),
        ({"variable": "head", "change": (0, 3)}, "diverging"),
    ],
)
def test_the_interactive_colours_follow_the_static_scale(stored_run, panel, kind):
    out = data(stored_run, **panel)
    shown, colors = frame.interactive_color(out, THEME)
    assert len(shown) == len(out.table)
    if kind == "classes":
        assert colors["cmax"] == len(out.classes) - 0.5
        assert colors["colorbar"]["ticktext"] == [name for _, name in out.classes]
    elif kind == "log":
        assert np.allclose(shown, np.log10(out.table["value"]))
        assert colors["colorbar"]["ticktext"][0] == f"{10 ** colors['cmin']:.3g}"
    else:
        assert colors["cmid"] == 0.0


def test_the_interactive_map_hovers_name_the_cell_and_its_value_or_class(stored_run):
    assert frame.hover_text(data(stored_run, variable="head"))[0].startswith("cell 0: ")
    classed = data(stored_run, variable="seepage_mask")
    names = {name for _, name in classed.classes}
    assert {t.split(": ")[1] for t in frame.hover_text(classed)} <= names


def test_the_interactive_map_is_one_mesh_and_refuses_a_table_of_reaches(stored_run):
    pytest.importorskip("plotly")
    traces, layout = frame.draw_interactive(data(stored_run, variable="head"), THEME)
    assert len(traces) == 1 and layout["scene"]["zaxis"] == {"visible": False, "range": [-1, 1]}
    assert layout["scene"]["xaxis"]["title"].startswith("x (")
    with pytest.raises(FigureNotApplicable, match="static engine only"):
        frame.draw_interactive(data(stored_run, variable="sfr_reaches.strahler"), THEME)
