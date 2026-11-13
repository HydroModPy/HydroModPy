"""The section frame on the small stored run: cut lengths, layer stack, values and the drawn artists."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from matplotlib.collections import PolyCollection
from matplotlib.colors import BoundaryNorm, LogNorm

from hydromodpy.display import static
from hydromodpy.display.frames import section
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from tests.unit.display._stored_run import HEAD_TOP, STEP, X0, Y0

THEME = THEMES["default"]
LINE = [(X0 + 100.0, Y0 + 750.0), (X0 + 1700.0, Y0 + 750.0)]
"""West to east through the middle row, from inside cell 4 to inside cell 7."""


def data(run, **panel):
    panel = {"line": LINE, **panel}
    return section.data(run, PanelRequest(type="section", **panel))


def test_the_pieces_follow_the_line_and_sum_to_its_length(stored_run):
    out = data(stored_run, variable="head")
    first = out.table[out.table["layer"] == 0]
    assert list(first["cell"]) == [4, 5, 6, 7]
    assert (np.diff(first["start"]) > 0).all()
    np.testing.assert_allclose(first["end"].iloc[:-1], first["start"].iloc[1:])
    np.testing.assert_allclose(first["end"] - first["start"], [STEP - 100, STEP, STEP, 200.0])
    assert first["end"].iloc[-1] == pytest.approx(1600.0)


def test_the_two_layers_stack_and_a_value_is_the_stored_head_of_its_layer(stored_run):
    table = data(stored_run, variable="head").table
    upper, lower = (table[table["layer"] == k].reset_index() for k in (0, 1))
    np.testing.assert_allclose(upper["bottom"], lower["top"])
    np.testing.assert_allclose([upper["top"].max(), lower["bottom"].min()], [120.0, 0.0])
    stored = np.asarray(stored_run.read("head", time="last"), float)
    for layer, cell in ((0, 5), (1, 6)):
        row = table[(table["layer"] == layer) & (table["cell"] == cell)]
        assert row["value"].iloc[0] == pytest.approx(stored[layer, cell])
    assert stored[0, 5] == pytest.approx(HEAD_TOP[5] + 2.0)


def test_a_head_gives_a_water_table_line_and_an_elevation_a_line_without_values(stored_run):
    out = data(stored_run, variable="head")
    assert out.line_label == "Water table" and out.line["start"].is_monotonic_increasing
    np.testing.assert_allclose(out.line["value"], HEAD_TOP[[4, 5, 6, 7]] + 2.0)
    top = data(stored_run, variable="topography")
    assert top.table["value"].isna().all()
    np.testing.assert_allclose(top.line["value"], HEAD_TOP[[4, 5, 6, 7]] + 8.0)


def test_a_line_along_a_shared_edge_keeps_one_cell_and_its_full_length(stored_run):
    edge = [(X0 + 100.0, Y0 + STEP), (X0 + 1600.0, Y0 + STEP)]
    first = data(stored_run, variable="head", line=edge).table.query("layer == 0")
    assert list(first["cell"]) == [0, 1, 2, 3]
    assert (first["end"] - first["start"]).sum() == pytest.approx(1500.0)


def test_the_default_line_runs_from_the_outlet_to_the_farthest_catchment_centre():
    centres = np.array([[1.0, 0.0], [3.0, 4.0], [9.0, 9.0]])
    zones = {"catchment": centres[:, 0] < 5}
    mesh = SimpleNamespace(outlet=(0.0, 0.0), centres=centres, zones=zones)
    panel = PanelRequest(type="section", variable=["head"])
    assert section._trace(panel, mesh) == ((0.0, 0.0), (3.0, 4.0))


REFUSED = [
    ({"variable": "head", "layer": 0}, "layer"),
    ({"variable": "head", "time": [0, 1]}, "one instant"),
    ({"variable": "head", "overlays": ["outline"]}, "marks"),
    ({"variable": "head", "line": None}, "needs a `line`"),
    ({"variable": "head", "line": [(0.0, 0.0), (1.0, 1.0)]}, "does not cross"),
]


@pytest.mark.parametrize(("panel", "word"), REFUSED)
def test_what_a_section_cannot_show_is_refused(stored_run, panel, word):
    with pytest.raises(FigureNotApplicable, match=word):
        data(stored_run, **panel)


def test_draw_adds_the_cells_the_lines_and_a_colorbar(stored_run):
    fig = static.new_figure(THEME)
    ax = fig.axes[0]
    section.draw(ax, data(stored_run, variable="head"), THEME)
    cells = [c for c in ax.collections if isinstance(c, PolyCollection)]
    assert len(cells) == 1 and len(cells[0].get_paths()) == 8 and cells[0].get_rasterized()
    assert {"Land surface", "Model base", "Layer interface"} <= set(
        ax.get_legend_handles_labels()[1]
    )
    assert len(fig.axes) == 2
    assert ax.get_xlabel() == "Distance along the section (m)"
    assert any("exaggeration about x" in t.get_text() for t in ax.texts)


def test_a_log_scale_and_a_class_scale_set_the_colour_norm(stored_run):
    ax = static.new_figure(THEME).axes[0]
    section.draw(ax, data(stored_run, variable="topography"), THEME)
    assert len(ax.figure.axes) == 1  # an elevation has no colour bar
    out = data(stored_run, variable="head", scale="log")
    ax = static.new_figure(THEME).axes[0]
    section.draw(ax, out, THEME)
    assert isinstance(ax.collections[0].norm, LogNorm)
    layers = out.table.assign(value=out.table["layer"].astype(float))
    classed = replace(
        out, scale="categorical", log=False, classes=((0, "a"), (1, "b")), table=layers
    )
    ax = static.new_figure(THEME).axes[0]
    section.draw(ax, classed, THEME)
    assert isinstance(ax.collections[0].norm, BoundaryNorm)
