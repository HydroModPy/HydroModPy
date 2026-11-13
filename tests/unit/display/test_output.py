"""``output.write`` and the ledger round trip, on the small stored run."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import output
from hydromodpy.display.catalog_figures import regen_figures
from hydromodpy.display.png_metadata import read_png_metadata
from hydromodpy.display.request import FigureRequest, expand
from hydromodpy.display.runs import figures_dir_of, record_figure
from hydromodpy.results.identity import PNG_IDENTITY_KEY
from hydromodpy.results.ledger import Ledger, record_derived_file


def entries(run):
    return {e.file: e for e in Ledger.read(figures_dir_of(run.dir)).entries}


def test_a_saved_figure_is_stamped_and_recorded_with_its_theme(stored_run):
    folder = figures_dir_of(stored_run.dir)
    path = stored_run.figure("head", time="last", theme="dark", formats=["png", "svg"], save=folder)
    assert PNG_IDENTITY_KEY in read_png_metadata(path)
    found = entries(stored_run)
    assert {"head.png", "head.svg"} <= set(found)
    options = found["head.png"].options
    assert options["theme"] == "dark" and options["request"]["panels"][0]["variable"] == ["head"]
    assert found["head.png"].identity.period is not None


def test_a_regeneration_replays_new_and_old_entries_and_skips_the_one_that_fails(stored_run):
    folder = figures_dir_of(stored_run.dir)
    stored_run.figure("recharge", time="last", save=folder)
    old = stored_run.figure("water_budget", save=folder)
    record_figure(old, name="water_budget", options={}, sim=stored_run, figures_dir=folder)
    identity = entries(stored_run)["recharge.png"].identity
    stale = {"request": {"variable": ["heed"], "name": "stale"}, "preset": None}
    (folder / "stale.png").write_bytes((folder / "recharge.png").read_bytes())
    record_derived_file(
        folder, folder / "stale.png", producer=output.PRODUCER, options=stale, identity=identity
    )
    before = (folder / "recharge.png").stat().st_mtime_ns
    written = regen_figures(stored_run.name, workspace=stored_run.dir.parent.parent)
    names = {path.name for path in written}
    assert {"recharge.png", "water_budget.png"} <= names and "stale.png" not in names
    assert (folder / "recharge.png").stat().st_mtime_ns > before


def test_a_regeneration_redraws_the_html_of_a_request_with_two_engines(stored_run):
    folder = figures_dir_of(stored_run.dir)
    both = {"name": "head", "variable": "head", "time": "last", "engine": ["static", "interactive"]}
    stored_run.figure(both, save=folder)
    before = (folder / "head.html").stat().st_mtime_ns
    written = {
        p.name for p in regen_figures(stored_run.name, workspace=stored_run.dir.parent.parent)
    }
    assert {"head.png", "head.html"} <= written
    assert (folder / "head.html").stat().st_mtime_ns > before


def test_the_ledger_replays_the_same_panels_and_a_bare_draw_does_not():
    figure = expand(FigureRequest(variable=["head"], name="h"), {})
    request = output.request_from_ledger(output.ledger_options(figure))
    assert expand(request, {}).panels == figure.panels
    bare = output.ledger_options(expand(FigureRequest(draw=lambda s, ax, t: None), {}))
    assert bare["request"] is None
    with pytest.raises(DisplayError, match="cannot be replayed"):
        output.request_from_ledger(bare)
    with pytest.raises(DisplayError, match="display:figure"):
        output.request_from_ledger({})
