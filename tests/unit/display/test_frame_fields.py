"""Every panel field is read or refused by every frame, on every branch, never ignored silently."""

from __future__ import annotations

import importlib
from dataclasses import fields

import pandas as pd
import pytest

from hydromodpy.display.request import FRAMES, PANEL_FIELDS, PanelRequest
from hydromodpy.display.subject import FigureNotApplicable
from tests._helpers.run_builders import GAUGE
from tests.unit.display._stored_run import X0, Y0

SAMPLES = {
    "time": "last", "layer": 0, "station": "zone:catchment", "overlays": ["outline"],
    "bbox": (0.0, 0.0, 1.0, 1.0), "line": [(0.0, 0.0), (1.0, 1.0)], "contours": True,
    "observed": True, "scores": True, "scale": "log", "stack": True, "by": "month",
    "reference": ["zero"], "share": True, "reduce": "mean", "change": (0, 1),
    "against": "observed", "cumulative": True,
}  # fmt: skip
IMPLEMENTED = [*(name for name, found in FRAMES.items() if found.ready), "table"]
ZONE, DOMAIN, WINDOW = "zone:catchment", "zone:domain", ["2001-02-01", "2001-03-01"]
LINE = [(X0 + 100.0, Y0 + 750.0), (X0 + 1700.0, Y0 + 750.0)]
SERIES = {"variable": ["discharge"], "station": GAUGE}
EVERY = {"time": WINDOW, "layer": 1, "observed": True, "scale": "log", "reduce": "mean"}
BRANCHES = [
    ("section", {"variable": "head", "line": LINE},
     {"time": 0, "overlays": ["lake"], "line": LINE[::-1], "scale": "log", "reduce": "mean",
      "change": (0, 3)}),
    ("distribution", {"variable": "head"}, {**EVERY, "station": DOMAIN, "cumulative": True}),
    ("distribution", {**SERIES, "variable": "discharge"}, {**EVERY, "against": "observed"}),
    ("xy", {**SERIES, "observed": True},
     {"time": WINDOW, "layer": 1, "scores": True, "scale": "log", "reference": ["one_to_one"]}),
    ("xy", {"variable": ["discharge", "rainfall"], "station": GAUGE},
     {"station": ZONE, "observed": True, "scale": "log", "reference": ["zero"]}),
    ("xy", {"variable": ["recharge", "drain"], "station": ZONE}, {"time": 0, "layer": 1}),
    ("groups", {"variable": ["budget"], "station": ZONE, "reduce": "mean"},
     {**EVERY, "reduce": "max", "stack": True, "by": "month"}),
    ("groups", {**SERIES, "variable": "discharge", "by": "month"}, {**EVERY, "stack": True}),
    ("groups", {"variable": "head", "by": "time"}, {**EVERY, "station": DOMAIN, "reduce": "mean"}),
    ("groups", {"variable": "seepage_mask", "station": ZONE}, {"layer": 1, "station": DOMAIN}),
    ("series", SERIES, {**EVERY, "station": ZONE, "scores": True, "stack": True,
                        "reference": ["zero"], "against": "observed", "cumulative": True}),
    ("volume", {"variable": ["head"]}, {"time": 0, "layer": 1}),
    ("map", {"variable": ["head"]},
     {"time": 0, "layer": 1, "bbox": (X0, Y0, X0 + 600, Y0 + 600), "contours": False,
      "scale": "log", "reduce": "mean", "change": (0, 3), "against": "observed"}),
]  # fmt: skip
RENDERED = {"share", "overlays"}


def shown(out) -> list[str]:
    values = (getattr(out, f.name) for f in fields(out))
    return [v.to_json() if isinstance(v, pd.DataFrame) else repr(v) for v in values]


def _module(frame):
    return importlib.import_module(f"hydromodpy.display.frames.{frame}")


@pytest.mark.parametrize("frame", IMPLEMENTED)
@pytest.mark.parametrize("field", [f for f in PANEL_FIELDS if f not in ("type", "variable")])
def test_a_field_is_used_or_refused_by_name(stored_run, frame, field):
    module = _module(frame)
    if field in module.FIELDS:
        return
    panel = PanelRequest(type=frame, variable=["head"], **{field: SAMPLES[field]})
    with pytest.raises(FigureNotApplicable, match=rf"{frame} panel does not take '{field}'"):
        module.data(stored_run, panel)


@pytest.mark.parametrize(
    ("frame", "base", "field", "value"),
    [(f, base, k, v) for f, base, tries in BRANCHES for k, v in tries.items()],
)
def test_a_listed_field_changes_the_data_or_is_refused(stored_run, frame, base, field, value):
    read = _module(frame).data
    plain = read(stored_run, PanelRequest(type=frame, **base))
    try:
        out = read(stored_run, PanelRequest(type=frame, **{**base, field: value}))
    except FigureNotApplicable:
        return
    assert shown(out) != shown(plain)


@pytest.mark.parametrize("frame", [f for f in IMPLEMENTED if f != "table"])
def test_every_listed_field_has_a_branch_that_tries_it(frame):
    module = _module(frame)
    tried = {k for f, _, tries in BRANCHES if f == frame for k in tries}
    assert set(module.FIELDS) - {"variable"} - RENDERED <= tried
