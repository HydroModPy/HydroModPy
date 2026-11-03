"""An evaluated run is a calibrated run scored out of its calibration window.

``Project.best`` and ``[sites.summary] best = "calibrated"`` kept the runs
labelled ``calibrated`` only, so the split-sample run of a site, the one
scored on days the search never saw, fell out of its best calibrated case.
Both now keep ``evaluated`` too; ``label="calibrated"`` still asks for the
in-window runs alone.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.project.summary import collect_project
from hydromodpy.results.checks import CalibratedBy
from hydromodpy.results.validity_rules import CALIBRATED_LABELS
from tests._helpers.sealed_runs import seal_run, write_session_dir
from tests._helpers.session_documents import calibration_window
from tests.unit.api.test_project_reads_a_campaign import _campaign

pytestmark = pytest.mark.fast

CALIBRATION_WINDOWS = calibration_window(date(2010, 1, 1), date(2014, 12, 31))


def _evaluated_campaign(tmp_path: Path) -> tuple[Path, str]:
    """Seal one exploratory and one evaluated case of nancon."""
    project = _campaign(tmp_path)
    proj = hmp.open(project)
    proj.plan()
    seal_run(project, "nancon-base", site="nancon", recipe="base", nse=0.52)
    evaluated = seal_run(
        project,
        "nancon-k2e_5",
        site="nancon",
        recipe="k2e_5",
        nse=0.81,
        parameters={"K": 2e-5},
        calibrated_by=CalibratedBy(
            session_id="s-nancon",
            phase="steady_k",
            trial=2,
            session_status="completed",
            windows=CALIBRATION_WINDOWS,
        ),
    )
    write_session_dir(
        project,
        "nancon-k2e_5",
        session_id="s-nancon",
        case_id="nancon-k2e_5",
        site="nancon",
        trials=3,
        best_trial=2,
        best_sim_id=evaluated,
        best_rel_dir="runs/nancon-k2e_5",
    )
    proj.close()
    return project, evaluated


def test_the_calibrated_labels_are_calibrated_and_evaluated() -> None:
    assert set(CALIBRATED_LABELS) == {"calibrated", "evaluated"}


def test_project_best_keeps_an_evaluated_run(tmp_path: Path) -> None:
    project, evaluated = _evaluated_campaign(tmp_path)

    with hmp.open(project) as proj:
        assert proj.cases.set_index("case_id").loc["nancon-k2e_5", "label"] == "evaluated"
        best = proj.best_runs("nse", by="site")
        in_window = proj.best_runs("nse", by="site", label="calibrated")

    assert list(best["sim_id"]) == [evaluated]
    assert best.iloc[0]["label"] == "evaluated"
    assert in_window.empty


def test_the_site_summary_keeps_an_evaluated_case(tmp_path: Path) -> None:
    project, _ = _evaluated_campaign(tmp_path)

    collect_project(project)

    by_site = pd.read_parquet(project / "summary" / "by_site.parquet").set_index("site")
    assert by_site.loc["nancon", "best_case"] == "nancon-k2e_5"
