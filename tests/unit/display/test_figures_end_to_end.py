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
from hydromodpy.display.frames.distribution import EXCEEDANCE_COLUMNS, HISTOGRAM_COLUMNS
from hydromodpy.display.frames.groups import GROUPS_COLUMNS
from hydromodpy.display.frames.map import MAP_COLUMNS
from hydromodpy.display.frames.section import SECTION_COLUMNS
from hydromodpy.display.frames.xy import XY_COLUMNS
from hydromodpy.display.render import render
from hydromodpy.display.request import (
    FRAMES,
    OVERLAY_FIELDS,
    FigureRequest,
    expand,
    shape_of,
)
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import get_theme
from hydromodpy.project.show import project_theme
from hydromodpy.results.field_registry import FIELD_REGISTRY, TIME_SERIES_REGISTRY
from tests._helpers.run_builders import GAUGE
from tests.unit.display._stored_run import AREAS, RECHARGE_M3S, X0, Y0

HELD = (
    "head", "recharge", "drain", "topography", "watertable_elevation", "watertable_depth",
    "seepage_mask", "discharge",
)  # fmt: skip
LINE = [(X0 + 100.0, Y0 + 750.0), (X0 + 1700.0, Y0 + 750.0)]
HISTOGRAM_OR_CURVE = (HISTOGRAM_COLUMNS, EXCEEDANCE_COLUMNS)
COLUMNS = {
    "map": (MAP_COLUMNS,),
    "series": (("time", "variable", "station", "simulated"),),
    "section": (SECTION_COLUMNS,),
    "xy": (XY_COLUMNS,),
    "distribution": HISTOGRAM_OR_CURVE,
    "groups": (GROUPS_COLUMNS,),
}
NOT_DRAWN = {
    ("topography", "series"), ("topography", "groups"), ("watertable_depth", "section"),
    ("seepage_mask", "section"), ("seepage_mask", "distribution"),
}  # fmt: skip
# Pairs the shape accepts and the variable refuses: a static field has no series, a mask has
# no layer axis and no values to bin.


def _cases() -> list[tuple[str, str]]:
    return [
        (name, frame)
        for name in HELD
        for frame in FRAMES
        if shape_of(name) in FRAMES[frame].shapes
        or (frame == "series" and FIELD_REGISTRY.get(name) and FIELD_REGISTRY[name].timed)
    ]


def _request(name: str, frame: str) -> dict:
    fields: dict = {"type": frame, "variable": [name]}
    if frame in ("series", "distribution", "groups"):
        fields["station"] = GAUGE if name == "discharge" else "zone:catchment"
    if frame == "section":
        fields["line"] = LINE
    elif frame == "xy":
        fields |= {"observed": True} if name == "discharge" else {"variable": [name, "topography"]}
        fields["station"] = GAUGE if name == "discharge" else None
    elif frame == "groups" and name != "seepage_mask":
        fields |= {"reduce": "mean"} if name == "discharge" else {"by": "time"}
    return {"name": "case", **fields}


@pytest.mark.parametrize(("name", "frame"), _cases())
def test_each_held_variable_draws_and_gives_its_table(stored_run, name, frame):
    request = _request(name, frame)
    if (name, frame) in NOT_DRAWN:
        with pytest.raises(FigureNotApplicable):
            stored_run.figure(request=request, data=True)
        return
    tables = stored_run.figure(request=request, data=True)
    assert list(tables) == ["a"]
    assert tuple(tables["a"].columns) in COLUMNS[frame]
    numbers = tables["a"].select_dtypes("number").to_numpy(float)
    assert np.isfinite(numbers).any()
    figure = stored_run.figure(request=request)
    assert isinstance(figure, Figure) and figure.axes


def test_a_recharge_flow_shows_in_mm_per_day(stored_run):
    table = stored_run.figure("recharge", time="last", data=True)["a"]
    expected = RECHARGE_M3S * 1.3 / AREAS * 86400 * 1000
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
