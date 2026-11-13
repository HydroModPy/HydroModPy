"""``output.write`` and the ledger round trip, on the small stored run."""

from __future__ import annotations

from datetime import date

import pytest

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import output
from hydromodpy.display.catalog_figures import regen_figures
from hydromodpy.display.request import FigureRequest, expand
from hydromodpy.display.runs import figures_dir_of
from hydromodpy.display.runs import regen_figures as regen_run
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger, record_derived_file


def entries(run):
    return {e.file: e for e in Ledger.read(figures_dir_of(run.dir)).entries}


def test_a_saved_figure_is_stamped_and_recorded_with_its_theme(stored_run):
    folder = figures_dir_of(stored_run.dir)
    path = stored_run.figure("head", time="last", theme="dark", formats=["png", "svg"], save=folder)
    assert read_identity_from(path) is not None
    found = entries(stored_run)
    assert {"head.png", "head.svg"} <= set(found)
    options = found["head.png"].options
    assert options["theme"] == "dark" and options["request"]["panels"][0]["variable"] == ["head"]
    assert found["head.png"].identity.period is not None


def test_a_regeneration_replays_requests_and_skips_the_one_that_fails(stored_run):
    folder = figures_dir_of(stored_run.dir)
    stored_run.figure("recharge", time="last", save=folder)
    identity = entries(stored_run)["recharge.png"].identity
    stale = {"request": {"variable": ["heed"], "name": "stale"}, "preset": None}
    (folder / "stale.png").write_bytes((folder / "recharge.png").read_bytes())
    record_derived_file(
        folder, folder / "stale.png", producer=output.PRODUCER, options=stale, identity=identity
    )
    before = (folder / "recharge.png").stat().st_mtime_ns
    written = regen_figures(stored_run.name, workspace=stored_run.dir.parent.parent)
    names = {path.name for path in written}
    assert "recharge.png" in names and "stale.png" not in names
    assert (folder / "recharge.png").stat().st_mtime_ns > before


def test_a_regeneration_skips_the_entry_of_a_figure_of_a_pre_release(stored_run):
    folder = figures_dir_of(stored_run.dir)
    stored_run.figure("recharge", time="last", save=folder)
    identity = entries(stored_run)["recharge.png"].identity
    (folder / "piezo.png").write_bytes((folder / "recharge.png").read_bytes())
    record_derived_file(
        folder,
        folder / "piezo.png",
        producer=f"{output.PRODUCER_PREFIX}piezometric_map",
        options={},
        identity=identity,
    )
    report = regen_run(stored_run, stored_run.dir)
    assert "recharge" in report.rendered  # the shared run may hold figures of earlier tests
    (skipped,) = report.skipped
    assert skipped.name == "piezo"
    assert "figures/index.json records piezo.png from the figure 'piezometric_map' of a" in (
        skipped.reason
    )
    assert "hmp show <run> --figure <variable or preset> --to piezo.png" in skipped.reason
    assert "watertable_elevation" in skipped.reason


def test_stamping_twice_keeps_one_strip(tmp_path):
    from PIL import Image

    from tests._helpers.run_records import make_identity

    sealed = make_identity().labelled("evaluated", label_date=date(2026, 11, 11), rule_version="1")
    path = tmp_path / "map.png"
    Image.new("RGB", (400, 100), "white").save(path)
    output.stamp_png_identity(path, make_identity())
    with Image.open(path) as image:
        first = image.size
    output.stamp_png_identity(path, sealed)
    with Image.open(path) as image:
        assert image.size == first
    assert read_identity_from(path).label == "evaluated"


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
