"""One search of a calibration (`runners.search`), played on the analytic bowl.

The bowl runs no model, so a zoomed Latin hypercube plays whole through
``run_calibration_cli`` in a second.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from tests.unit.calibration._factories_runners import write_document

ZOOM = """
[calibration]
method = "lhs_zoom"
max_trials = "auto"
seed = 7
parallel = 4
evaluator = "analytic_bowl"
use_cache = false
{section}

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"
"""


def _run(tmp_path: Path, section: str = ""):
    text = ZOOM.format(section=section)
    return run_calibration_cli(write_document(tmp_path, text), workspace=tmp_path)


def test_a_zoom_spends_its_levels_and_reports_each_box(tmp_path: Path) -> None:
    report = _run(tmp_path, '[calibration.uncertainty]\ncost_margin = "10%"\n')

    zoom = report.extra["zoom"]
    assert report.method == "lhs_zoom"
    assert report.n_trials == 40
    assert report.extra["search"]["stop_state"] == "plan_exhausted"
    assert [level["size"] for level in zoom] == [24, 16]
    assert (zoom[0]["low"], zoom[0]["high"]) == pytest.approx((1e-6, 1e-3))
    assert zoom[1]["narrowed"] is True
    assert zoom[1]["low"] > 1e-6 or zoom[1]["high"] < 1e-3
    assert zoom[1]["n_within"] >= 1


def test_the_margin_of_the_phase_is_the_margin_of_the_zoom(tmp_path: Path) -> None:
    report = _run(tmp_path, '[calibration.uncertainty]\ncost_margin = "10%"\n')

    zoom = report.extra["zoom"][1]
    assert (zoom["margin"], zoom["margin_kind"]) == (0.1, "relative")
    assert report.extra["interval_width"]["margin"] == 0.1
    assert zoom["threshold"] == pytest.approx(zoom["best_cost"] * 1.1)


def test_a_zoom_without_a_margin_reads_five_per_cent(tmp_path: Path) -> None:
    report = _run(tmp_path)

    assert report.extra["zoom"][1]["margin"] == 0.05
    assert report.extra["interval_width"]["source"] == "default"


def test_the_margin_is_no_option_of_the_journal(tmp_path: Path) -> None:
    report = _run(tmp_path)

    session = next(tmp_path.rglob("session.json")).read_text(encoding="utf-8")
    assert "IntervalWidth" not in session
    assert report.n_trials == 40


def test_levels_written_in_the_file_size_the_budget(tmp_path: Path) -> None:
    report = _run(tmp_path, "method_options = { levels = [8, 4, 4] }")

    assert report.n_trials == 16
    assert [level["size"] for level in report.extra["zoom"]] == [8, 4, 4]
