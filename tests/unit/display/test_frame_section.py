"""The section frame on the small stored run: cut lengths, layer stack, values and the drawn artists."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from matplotlib.collections import PolyCollection
from matplotlib.colors import BoundaryNorm, LogNorm
from shapely.geometry import LineString

from hydromodpy.display import static, variables
from hydromodpy.display.frames import section
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES, colormap
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
    out = data(stored_run, variable="head")
    section.draw(ax, out, THEME)
    cells = [c for c in ax.collections if isinstance(c, PolyCollection)]
    assert len(cells) == 1 and len(cells[0].get_paths()) == 8 and cells[0].get_rasterized()
    assert ax.get_legend_handles_labels()[1] == [
        "Layer interface", "Model base", "Land surface", "Water table",
    ]  # fmt: skip
    assert len(fig.axes) == 2 and fig.axes[1].get_ylabel() == ""
    assert ax.get_xlabel() == "Distance along the section (m)"
    assert ax.get_title(loc="left") == out.label
    when = ax.get_title(loc="right")
    assert when.startswith("April 2001, west to east, 1.6 km, vertical exaggeration x")
    assert ax.get_ylim() == pytest.approx((-4.8, 124.8))  # the whole model, coloured


def test_a_water_table_alone_fills_the_saturated_and_the_unsaturated_zone(stored_run):
    out = data(stored_run, variable="watertable_elevation", time="first")
    assert out.water and (out.period, out.caption) == ("January 2001", "west to east, 1.6 km")
    assert not data(stored_run, variable="topography").water
    ax = static.new_figure(THEME).axes[0]
    section.draw(ax, out, THEME)
    # The two fills carry no legend entry, and the model base is under the frame.
    assert ax.get_legend_handles_labels()[1] == ["Land surface", "Water table"]
    saturated, unsaturated = (c.get_paths()[0].vertices[:, 1] for c in ax.collections)
    water = float(out.line["value"].iloc[0])
    assert (saturated.min(), saturated.max()) == pytest.approx((0.0, out.line["value"].max()))
    assert (unsaturated.min(), unsaturated.max()) == pytest.approx((water, 120.0))
    assert out.line["value"].is_monotonic_increasing
    assert len(ax.figure.axes) == 1  # no cell is coloured, so no colour bar
    # Each line is one step per piece of cell, and the two profiles are thick.
    table = ax.lines[-1]
    np.testing.assert_allclose(table.get_xdata(), out.line[["start", "end"]].to_numpy().ravel())
    np.testing.assert_allclose(table.get_ydata(), np.repeat(out.line["value"].to_numpy(), 2))
    assert table.get_linewidth() == pytest.approx(section.PROFILE * THEME.data_line_width)
    # 100 m of aquifer lie under a water table 18 m under the ground, so the view is cut
    # a little under the water table.
    low = water - section.UNDER * (120.0 - water)
    assert ax.get_ylim()[0] == pytest.approx(low - 0.04 * (120.0 - low))
    assert any("Model base at 0 to 0 m, under the frame" in t.get_text() for t in ax.texts)
    whole = data(stored_run, variable="watertable_elevation", bbox=(0.0, 0.0, 800.0, 130.0))
    ax = static.new_figure(THEME).axes[0]
    section.draw(ax, whole, THEME)
    assert (*ax.get_xlim(), *ax.get_ylim()) == (0.0, 800.0, 0.0, 130.0)


def test_seepage_marks_one_point_per_cell_on_the_land_surface(stored_run, monkeypatch):
    stored = section.read_field

    def field(run, name, **kwargs):
        if name == "seepage_mask":
            return (np.arange(12) == 5).astype(float)
        return stored(run, name, **kwargs)

    monkeypatch.setattr(section, "read_field", field)
    out = data(stored_run, variable="watertable_elevation", overlays=["seepage"])
    assert out.marks == (("seepage", STEP - 100, 2 * STEP - 100),)
    assert data(stored_run, variable="topography", overlays=["seepage"]).marks == ()
    ax = static.new_figure(THEME).axes[0]
    section.draw(ax, out, THEME)
    points = [c for c in ax.collections if c.get_label() == "Seepage"]
    np.testing.assert_allclose(points[0].get_offsets(), [[1.5 * STEP - 100, 120.0]])


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


def test_a_frequency_section_is_a_share_and_a_one_signed_flow_is_sequential(stored_run):
    share = data(stored_run, variable="recharge", reduce="frequency")
    assert share.label == variables.FREQUENCY_LABEL and share.scale == "sequential"
    np.testing.assert_allclose(
        share.table.query("layer == 0")["value"], 1.0
    )  # recharge is in layer 0
    flow = data(stored_run, variable="recharge")
    assert flow.scale == "sequential" and not flow.log
    ax = static.new_figure(THEME).axes[0]
    section.draw(ax, flow, THEME)
    assert ax.collections[0].get_cmap().name == colormap(THEME.ramps["sequential"]).name


def test_a_mesh_without_layer_interfaces_has_no_section(stored_run, monkeypatch):
    real = section.read_mesh
    monkeypatch.setattr(section, "read_mesh", lambda run: replace(real(run), interfaces=None))
    with pytest.raises(FigureNotApplicable, match="no layer interfaces"):
        data(stored_run, variable="head")


def test_an_inactive_cell_on_the_line_is_left_out(stored_run, monkeypatch):
    real = section.read_mesh

    def without_cell_7(run):
        mesh = real(run)
        domain = mesh.zones["domain"].copy()
        domain[7] = False
        return replace(mesh, zones={**mesh.zones, "domain": domain})

    monkeypatch.setattr(section, "read_mesh", without_cell_7)
    table = data(stored_run, variable="head").table
    assert list(table.loc[table["layer"] == 0, "cell"]) == [4, 5, 6]


def test_a_head_section_without_a_water_table_draws_the_cells_alone(stored_run, monkeypatch):
    stored = section.stored_field

    def field(run, name, panel):
        if name == "watertable_elevation":
            raise FigureNotApplicable("no water table")
        return stored(run, name, panel)

    monkeypatch.setattr(section, "stored_field", field)
    out = data(stored_run, variable="head")
    assert out.line is None and not out.water


def test_a_line_that_only_touches_a_corner_cuts_no_piece_from_that_cell(stored_run):
    corner = [(X0 + 250.0, Y0 + 250.0), (X0 + 750.0, Y0 + 750.0)]
    out = data(stored_run, variable="head", line=corner)
    assert sorted(set(out.table["cell"])) == [0, 5]  # cells 1 and 4 meet it at the vertex only


def test_a_lake_is_one_span_over_its_cells_and_a_barrier_is_a_line_at_its_crossing(
    stored_run, monkeypatch
):
    stored = section.read_field

    def field(run, name, **kwargs):
        if name == "lake":
            return np.isin(np.arange(12), [4, 5, 6]).astype(float)
        return stored(run, name, **kwargs)

    wall = gpd.GeoDataFrame(geometry=[LineString([(X0 + 800.0, Y0), (X0 + 800.0, Y0 + 1500.0)])])
    monkeypatch.setattr(section, "read_field", field)
    monkeypatch.setattr(section, "read_network", lambda run, role: wall)
    out = data(stored_run, variable="head", overlays=["lake", "barrier"])
    (lake, barrier) = out.marks
    assert lake[0] == "lake" and lake[1:] == (pytest.approx(0.0), pytest.approx(1400.0))  # fmt: skip
    assert barrier == ("barrier", pytest.approx(700.0), pytest.approx(700.0))
    ax = static.new_figure(THEME).axes[0]
    section.draw(ax, out, THEME)
    labels = ax.get_legend_handles_labels()[1]
    assert "Lake" in labels and "Barrier" in labels
    assert any(line.get_linestyle() == ":" for line in ax.lines)
