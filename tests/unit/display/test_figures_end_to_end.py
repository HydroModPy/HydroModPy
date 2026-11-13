"""Figures drawn and read from one real stored run, through the public path.

The run of ``_stored_run.py`` holds a head, a recharge and a drain term, a topography,
a discharge at two stations with an observed record, and a descent basin.
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure

from hydromodpy.core.exceptions import CommandUsageError
from hydromodpy.display.render import render
from hydromodpy.display.request import (
    FRAMES,
    OVERLAY_FIELDS,
    FigureRequest,
    expand,
    shape_of,
)
from hydromodpy.display.theme import get_theme
from hydromodpy.project.show import project_theme
from hydromodpy.results.field_registry import FIELD_REGISTRY, TIME_SERIES_REGISTRY
from tests._helpers.run_builders import GAUGE
from tests.unit.display._stored_run import RECHARGE_M3S, STEP

HELD = (
    "head", "recharge", "drain", "topography", "watertable_elevation", "watertable_depth",
    "seepage_mask", "discharge",
)  # fmt: skip
STATION = {"discharge": GAUGE}


def _cases() -> list[tuple[str, str]]:
    found = []
    for name in HELD:
        shape = shape_of(name)
        for frame in ("map", "series"):
            if shape in FRAMES[frame].shapes:
                found.append((name, frame))
            elif frame == "series" and name in FIELD_REGISTRY and FIELD_REGISTRY[name].timed:
                found.append((name, frame))
    return found


def _fields(name: str, frame: str) -> dict:
    if frame == "series":
        return {"station": STATION.get(name, "zone:catchment")}
    return {}


@pytest.mark.parametrize(("name", "frame"), _cases())
def test_each_held_variable_draws_and_gives_its_table(stored_run, name, frame):
    fields = _fields(name, frame)
    tables = stored_run.figure_data(name, type=frame, **fields)
    column = "value" if frame == "map" else "simulated"
    assert list(tables) == ["a"]
    values = tables["a"][column].to_numpy(float)
    assert np.isfinite(values).any()
    if name == "head":
        assert frame == "map" or np.isfinite(values).all()
    figure = stored_run.figure(name, type=frame, **fields)
    assert isinstance(figure, Figure)
    assert figure.axes


def test_a_recharge_flow_shows_in_mm_per_day(stored_run):
    table = stored_run.figure_data("recharge", time="last")["a"]
    expected = RECHARGE_M3S * 1.3 / STEP**2 * 86400 * 1000
    assert table["value"].to_numpy() == pytest.approx(expected, rel=1e-4)


def test_render_accepts_a_resolved_request_and_the_old_path_still_draws(stored_run):
    figure = expand(FigureRequest(variable=["head"], time="last"), {})
    assert isinstance(render(figure, stored_run), Figure)
    assert isinstance(stored_run.figure("water_budget"), Figure)


def test_a_relief_keeps_the_map_equal_aspect_and_overlays_never_refuse(stored_run):
    figure = stored_run.figure("topography", overlays=sorted(OVERLAY_FIELDS))
    assert figure.axes[0].get_aspect() == 1.0


REFUSED = [
    ("budget", {}, "summed over a zone"),
    ("budget", {"station": GAUGE}, "summed over a zone"),
    ("budget", {"station": "zone:catchment", "type": "map"}, "drawn by a series"),
    ("heed", {}, "Did you mean head"),
    ("head", {"type": "map", "variable": "a.b"}, "map draws a column"),
]


@pytest.mark.parametrize(("name", "fields", "words"), REFUSED)
def test_a_request_the_figure_cannot_honour_is_refused_with_a_sentence(
    stored_run, name, fields, words
):
    with pytest.raises((ValueError, CommandUsageError), match=words):
        stored_run.figure(name, **fields)


def test_a_figure_takes_the_theme_of_the_sealed_display_of_the_run(stored_run):
    assert project_theme(stored_run) == "print"
    figure = stored_run.figure("head", time="last")
    assert figure.get_facecolor() == to_rgba(get_theme("print").face)
    assert stored_run.figure("head", theme="dark").get_facecolor() != figure.get_facecolor()
