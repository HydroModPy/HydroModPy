"""``render``, the one door of the figures, played on the small stored run."""

from __future__ import annotations

import dataclasses
from concurrent.futures import ThreadPoolExecutor

import pytest

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import render as door
from hydromodpy.display import static
from hydromodpy.display.request import FigureRequest, PanelRequest, expand
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import get_theme

HEAD = {"variable": ["head"]}


def figure(**fields):
    return FigureRequest(name="f", **fields)


@pytest.mark.parametrize(("count", "grid"), [(1, (1, 1)), (3, (1, 3)), (4, (2, 3)), (7, (3, 3))])
def test_panels_sit_in_one_row_up_to_three_then_wrap_and_carry_a_label(stored_run, count, grid):
    panels = [{**HEAD, "time": i % 4} for i in range(count)]
    fig = door.render(figure(panels=panels), stored_run)
    maps = [ax for ax in fig.axes if ax.get_label() != "<colorbar>"]
    assert len(maps) == count
    columns = {round(ax.get_position().x0, 3) for ax in maps}
    rows = {round(ax.get_position().y0, 3) for ax in maps}
    assert (len(rows), len(columns)) == grid
    labels = [t.get_text() for ax in maps for t in ax.texts if t.get_text().startswith("(")]
    assert labels == [f"({chr(97 + i)})" for i in range(count)] * (count > 1)


@pytest.mark.parametrize("share", [True, False])
def test_a_facet_shares_its_limits_on_request(stored_run, share):
    request = figure(facet="time", panels=[{**HEAD, "time": [0, 3], "share": share}])
    maps = [ax for ax in door.render(request, stored_run).axes if ax.collections]
    clims = [ax.collections[0].get_clim() for ax in maps]
    assert (clims[0] == clims[1]) is share


def test_data_tables_are_keyed_by_panel_and_by_facet_value(stored_run):
    assert list(door.render(figure(panels=[HEAD, HEAD]), stored_run, data=True)) == ["a", "b"]
    faceted = {"facet": "layer", "panels": [HEAD]}
    assert list(door.render(figure(**faceted), stored_run, data=True)) == ["a:0", "a:1"]
    both = figure(facet="variable", panels=[{"variable": ["head", "topography"]}])
    assert list(door.render(both, stored_run, data=True)) == ["a:head", "a:topography"]
    with pytest.raises(DisplayError, match="needs a set of runs"):
        door.render(figure(facet="run", panels=[HEAD]), stored_run)
    with pytest.raises(DisplayError, match="list of instants"):
        door.render(figure(facet="time", panels=[HEAD]), stored_run)


@pytest.mark.parametrize(
    ("fields", "word"),
    [
        ({"panels": [PanelRequest(type="volume", variable="head")]}, "volume"),
        ({"variable": "head", "when": "session"}, "session"),
        ({"panels": [PanelRequest(type="series", variable="head", layer=0)]}, "shape"),
    ],
)
def test_what_is_not_ready_is_refused_by_name(stored_run, fields, word):
    with pytest.raises(DisplayError, match=word):
        door.render(figure(**fields), stored_run)


def test_a_panel_that_cannot_be_drawn_refuses_the_figure_and_names_it(stored_run):
    request = figure(panels=[HEAD, {"variable": ["discharge"], "station": "nope"}])
    with pytest.raises(FigureNotApplicable, match="Panel b: .*Stations"):
        door.render(request, stored_run)


def test_a_draw_function_gets_only_the_keywords_it_declares(stored_run):
    seen = {}

    def few(subject, ax, theme, station):
        seen.update(station=station)

    def many(subject, ax, theme, **keywords):
        seen.update(keywords)

    for function in (few, many):
        drawn = dataclasses.replace(
            expand(FigureRequest(draw=function), {}),
            draw_keywords={"station": "g1", "time": "last"},
        )
        assert len(door.render(drawn, stored_run).axes) == 1
    assert seen == {"station": "g1", "time": "last"}
    with pytest.raises(DisplayError, match="no table of numbers"):
        door.render(FigureRequest(draw=few), stored_run, data=True)


def test_two_threads_write_the_same_bytes(stored_run, tmp_path):
    request = figure(panels=[{**HEAD, "time": 1}])

    def run(name):
        fig = door.render(request, stored_run)
        return static.save(fig, tmp_path / name, get_theme("default"))[0].read_bytes()

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(run, ["one", "two"])
    assert first == second
