"""The interactive engine: plotly traces hold the numbers of the tables, and refusals name themselves."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import interactive, output
from hydromodpy.display import render as door
from hydromodpy.display.request import FigureRequest, expand
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import get_theme
from tests._helpers.run_builders import GAUGE

SERIES = {"station": GAUGE, "observed": True}
CELLS, TOP_TRIANGLES, WALL_TRIANGLES = 12, 24, 28
"""The stored mesh is a 3 by 4 grid of quadrilaterals, 14 rim edges, two triangles each."""


def values_of(trace, per_cell: int = 4) -> np.ndarray:
    return np.asarray(trace.intensity, dtype=float)[::per_cell]


@pytest.mark.parametrize("name", ["head", "topography"])
def test_a_map_trace_holds_the_value_of_each_cell_and_the_static_scale(stored_run, name):
    table = stored_run.figure(name, time="last", data=True)["a"]
    trace = stored_run.figure(name, time="last", engine="interactive").data[0]
    np.testing.assert_allclose(values_of(trace), table["value"], rtol=1e-6)
    assert list(trace.text[::4]) == [f"cell {c}: {v:.4g}" for c, v in zip(table["cell"], table["value"])]  # fmt: skip
    drawn = stored_run.figure(name, time="last")
    bar = next(ax for ax in drawn.axes if ax.get_label() == "<colorbar>")
    assert (trace.cmin, trace.cmax) == pytest.approx(drawn.axes[0].collections[0].get_clim())
    assert trace.colorbar.title.text == interactive.plain(bar.get_ylabel()).replace("\n", "<br>")


def test_a_series_holds_the_simulated_values_and_the_observed_points(stored_run):
    table = stored_run.figure("discharge", **SERIES, data=True)["a"]
    simulated, observed = stored_run.figure("discharge", engine="interactive", **SERIES).data
    np.testing.assert_allclose(simulated.y, table["simulated"])
    seen = table.dropna(subset=["observed"])
    np.testing.assert_allclose(observed.y, seen["observed"])
    assert (observed.mode, observed.name) == ("markers", "observed")


def test_a_stacked_budget_draws_one_bar_per_term(stored_run):
    request = {"variable": "budget", "station": "zone:catchment", "stack": True}
    traces = stored_run.figure("budget", engine="interactive", **request).data
    assert {trace.type for trace in traces} == {"bar"}
    assert len(traces) == len(
        stored_run.figure("budget", **request, data=True)["a"]["variable"].unique()
    )


def test_the_block_has_a_top_per_cell_the_walls_and_one_row_per_cell(stored_run):
    table = stored_run.figure("head", type="volume", data=True)["a"]
    assert list(table.columns) == ["cell", "x", "y", "top", "bottom", "value"]
    assert len(table) == CELLS
    assert (table["top"] > table["bottom"]).all()
    fig = stored_run.figure("head", type="volume", engine="interactive")
    top, walls = fig.data
    assert (len(top.i), len(walls.i)) == (TOP_TRIANGLES, WALL_TRIANGLES)
    assert fig.layout.annotations[0].text.startswith("vertical exaggeration x")


def test_two_panels_keep_their_order_and_the_html_loads_plotly(stored_run, tmp_path):
    request = FigureRequest(name="pair", panels=[{"variable": "head"}, {"variable": "discharge"}])
    figure = expand(request, {})
    fig = door.render(figure, stored_run, engine="interactive")
    assert [a.text for a in fig.layout.annotations] == ["(a)", "(b)"]
    assert [t.type for t in fig.data] == ["mesh3d", "scatter"]
    theme = get_theme("default")
    cdn = output.write(fig, figure, None, tmp_path / "cdn", theme)[0]
    held = output.write(fig, figure, None, tmp_path / "held", theme, embed=True)[0]
    assert cdn.suffix == ".html" and "cdn.plot.ly" in cdn.read_text()
    assert held.stat().st_size > cdn.stat().st_size + 1_000_000


def test_a_request_with_two_engines_writes_one_file_per_engine(stored_run, tmp_path):
    figure = expand(
        FigureRequest(name="both", variable="head", engine=["static", "interactive"]), {}
    )
    assert figure.formats == ("png", "html")
    for engine in figure.engine:
        drawn = door.render(figure, stored_run, engine=engine)
        output.write(drawn, figure, None, tmp_path, get_theme("default"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["both.html", "both.png"]


@pytest.mark.parametrize(
    ("request_", "engine", "words"),
    [
        ({"variable": "head", "type": "volume"}, "static", ("volume", "engine = 'interactive'")),
        (
            {"variable": "head", "type": "section", "line": [(0, 0), (1, 1)]},
            "interactive",
            ("section", "map, series, volume"),
        ),  # fmt: skip
    ],
)
def test_a_frame_without_the_engine_refuses_and_names_itself(stored_run, request_, engine, words):
    with pytest.raises(DisplayError) as refusal:
        door.render(expand(FigureRequest(name="f", **request_), {}), stored_run, engine=engine)
    assert all(word in str(refusal.value) for word in words)


def test_a_drawn_function_and_a_special_figure_refuse_the_interactive_engine(stored_run):
    drawn = expand(FigureRequest(draw=lambda subject, ax, theme: None), {})
    with pytest.raises(DisplayError, match="static engine only.*map, series, volume"):
        door.render(drawn, stored_run, engine="interactive")


@pytest.mark.parametrize("kept", [{}, {"type": "volume"}])
def test_a_map_of_too_many_cells_refuses_and_names_the_count_and_the_limit(
    stored_run, monkeypatch, kept
):
    monkeypatch.setattr(interactive, "MAX_CELLS", 5)
    with pytest.raises(FigureNotApplicable, match=r"up to 5 cells.*has 12.*engine = 'static'"):
        stored_run.figure("head", engine="interactive", **kept)


@pytest.mark.parametrize("asked", [{"overlays": ["outlet"]}, {"contours": True}])
def test_the_interactive_map_refuses_what_only_the_static_engine_draws(stored_run, asked):
    with pytest.raises(FigureNotApplicable, match=r"does not draw.*static engine draws it"):
        stored_run.figure("head", engine="interactive", **asked)


@pytest.mark.parametrize(("layer", "top", "bottom"), [(None, 120, 0), (0, 120, 60), (1, 60, 0)])
def test_the_block_is_the_layer_asked_or_the_whole_column(stored_run, layer, top, bottom):
    kept = {} if layer is None else {"layer": layer}
    table = stored_run.figure("head", type="volume", **kept, data=True)["a"]
    assert (set(table["top"]), set(table["bottom"])) == ({top}, {bottom})
    ground, walls = stored_run.figure("head", type="volume", engine="interactive", **kept).data
    assert (len(ground.i), max(ground.z), min(walls.z)) == (TOP_TRIANGLES, top, bottom)


@pytest.mark.allow_subprocess
def test_the_request_and_its_validation_load_no_plotly():
    code = (
        "import sys, hydromodpy.display.request as r\n"
        "r.FigureRequest.model_validate({'variable': 'head', 'engine': 'interactive'})\n"
        "assert 'plotly' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
