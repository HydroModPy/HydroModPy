"""Figure requests written in TOML: parsing, expansion, stems, refusals, variables read."""

from __future__ import annotations

import subprocess
import sys
import tomllib

import pytest
from pydantic import ValidationError

from hydromodpy.display import request as rq
from hydromodpy.display.overlays import OVERLAYS
from hydromodpy.display.request import FigureRequest, expand

ZONE = 'station = "zone:catchment"'
PRESETS_OF_THE_ANNEX = {
    "hydrograph": [
        f'type = "series", variable = "recharge", {ZONE}, holes = ["time"]',
        'type = "series", variable = "discharge", observed = true, scores = true, '
        'scale = "linear", holes = ["variable", "station", "scale", "time"]',
    ],
}


def table(text: str) -> dict:
    return tomllib.loads(f"r = {{{text}}}")["r"]


PRESETS = {k: FigureRequest(panels=[table(t) for t in v]) for k, v in PRESETS_OF_THE_ANNEX.items()}


def ask(text: str) -> FigureRequest:
    return FigureRequest.model_validate(table(text))


@pytest.mark.parametrize(
    ("text", "frame"),
    [
        ('variable = "topography", overlays = ["relief", "outline", "outlet"]', "map"),
        ('variable = "watertable_depth", time = [2002-01-01, 2002-07-01], facet = "time"', "map"),
        ('variable = "seepage_mask", reduce = "frequency"', "map"),
        ('variable = "stage", observed = true, reference = [{value = 1, label = "w"}]', "series"),
    ],
)
def test_variable_requests_take_their_frame(text: str, frame: str) -> None:
    figure = rq.expand(request := ask(text), PRESETS)
    assert [panel.type for panel in figure.panels] == [frame]
    assert figure.stem == request.variable[0]
    assert rq.expand(rq.replay_request(figure), PRESETS).panels == figure.panels


def test_a_preset_fills_only_its_holes() -> None:
    figure = rq.expand(ask('preset = "hydrograph", variable = "stage", station = "x"'), PRESETS)
    assert [panel.variable for panel in figure.panels] == [["recharge"], ["stage"]]
    assert [panel.station for panel in figure.panels] == ["zone:catchment", "x"]
    assert (figure.stem, figure.width, figure.preset) == ("hydrograph", "double", "hydrograph")
    overlays = rq.expand(ask('variable = "head"'), PRESETS).panels[0].overlays
    assert overlays == ["outline", "outlet", "scale_bar"]


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ('variable = "head", type = "mapp"', "Known frames: map"),
        ('variable = "head", overlays = ["outlne"]', "Did you mean outline"),
        ('variable = "head", engine = "interactive", formats = ["png"]', "html"),
        ('variable = "head", when = "after:solve"', "Known steps: validate"),
        ('variable = "head", station = "zone:basin"', "zone:catchment"),
        ('variable = "head", time = "yesterday"', "YYYY-MM-DD"),
        ('variable = "head", change = ["first"]', "two instants"),
        ('variable = "head", layer = "mean"', "sum"),
        ('variable = "head", bbox = [10, 0, 0, 10]', "xmin, ymin"),
        ('variable = "head", every = 5', "when = 'trial'"),
        ('panels = [{variable = "head", holes = ["colour"]}]', "Known panel fields"),
        ('variable = "head", holes = ["variable"]', "holes"),
        ("", "variable, a preset, panels or draw"),
        ('preset = "hydrograph", panels = [{variable = "head"}]', "not preset and panels"),
        ('panels = [{variable = "head"}], station = "x"', "belong inside a panel"),
        ('panels = [{variable = "head"}, {variable = "stage"}], facet = "time"', "facet"),
        ('draw = "mypackage:my_figure"', "never written in a file"),
    ],
)
def test_requests_refused_at_parse(text: str, words: str) -> None:
    with pytest.raises(ValidationError, match=words):
        ask(text)


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ('variable = "hed"', "Did you mean head"),
        ('variable = "mass_balance.percent_error"', "write the frame"),
        ('variable = ["head", "stage"]', "different frames"),
        ('variable = "head", type = "table"', "table.column"),
        ('preset = "hydrogrph"', "Did you mean hydrograph"),
        ('preset = "hydrograph", by = "month"', "no hole 'by'"),
        ('panels = [{type = "map"}], name = "p"', "has no variable"),
        ('variable = "budget"', "summed over a zone"),
        ('variable = "head", type = "map", time = "2001-13-01"', "YYYY-MM-DD"),
    ],
)
def test_requests_refused_at_expand(text: str, words: str) -> None:
    with pytest.raises(ValueError, match=words):
        rq.expand(ask(text), PRESETS)


def test_an_unknown_preset_with_none_defined_says_so() -> None:
    with pytest.raises(ValueError, match="No preset is defined yet") as error:
        rq.expand(ask('preset = "mine"'), {})
    assert "Known presets: ." not in str(error.value)


def test_the_budget_expands_to_a_series_and_keeps_every_term_for_the_planner() -> None:
    request = ask(f'variable = "budget", {ZONE}')
    assert rq.expand(request, {}).panels[0].type == "series"
    assert {"recharge", "drain"} <= set(rq.required_variables(request, {}))


def test_file_stems_are_unique_or_named() -> None:
    head = [ask('variable = "head", layer = 0'), ask('variable = "head", layer = 1')]
    with pytest.raises(ValueError, match="Give each one its own name"):
        rq.check_stems(head)
    rq.check_stems([head[0], ask('variable = "head", layer = 1, name = "head_layer_1"')])
    with pytest.raises(ValueError, match="needs a name"):
        rq.file_stem(ask('panels = [{variable = "head"}]'))


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ('variable = "watertable_depth"', ("watertable_depth",)),
        ('variable = "topography", overlays = ["relief", "wells"]', ("topography", "well")),
        ('preset = "hydrograph", variable = "stage"', ("recharge", "stage")),
    ],
)
def test_required_variables(text: str, names: tuple[str, ...]) -> None:
    assert rq.required_variables(ask(text), PRESETS) == names


def test_draw_comes_from_python_only() -> None:
    def my_figure(subject, ax, theme):
        return None

    request = FigureRequest(draw=my_figure)
    assert rq.file_stem(request) == "my_figure"
    assert "draw" not in request.model_dump()
    assert "draw" not in FigureRequest.model_json_schema()["properties"]
    assert rq.expand(request, PRESETS).draw is my_figure
    with pytest.raises(ValueError, match="draw it again in Python"):
        rq.replay_request(rq.expand(request, PRESETS))


def test_the_request_loads_no_drawing_and_no_run_reader() -> None:
    code = "import sys, hydromodpy.display.request; print(*sys.modules)"
    loaded = set(subprocess.check_output([sys.executable, "-c", code], text=True).split())
    assert not {"matplotlib", "hydromodpy.results.run", "pandas"} & loaded
    assert set(OVERLAYS) == set(rq.OVERLAY_FIELDS)


def test_a_draw_function_takes_station_and_time_at_figure_level():
    def draw(subject, ax, theme, station=None, time=None):
        return None

    figure = expand(FigureRequest(draw=draw, station="lake:1", time="last"), {})
    assert figure.draw_keywords == {"station": "lake:1", "time": "last"}
    with pytest.raises(ValueError, match="belong inside a panel"):
        FigureRequest(draw=draw, layer=1)


def test_a_section_alone_is_drawn_at_double_width():
    figure = expand(FigureRequest(variable=["head"], type="section"), {})
    assert figure.width == "double"
