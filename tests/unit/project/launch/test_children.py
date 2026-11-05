"""The case processes of the launcher and what they leave behind.

A calibration case is as wide as its widest phase, a plan gives its cases their
workflow and their solves, and a private cache that cannot be merged into the
shared one fails its case only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.project.launch import local as launch_local
from hydromodpy.project.launch import plan_project, run_plan
from hydromodpy.project.launch.children import calibration_width
from tests.unit.project.launch._launch_fakes import (
    events,
    write_behaviour,
    write_project,
)


def test_a_calibration_counts_its_own_parallel_in_the_budget(tmp_path: Path) -> None:
    import pyarrow as pa

    from hydromodpy.results.plan_store import PlanCase, StoredPlan

    directory = tmp_path / "plan" / "abc"
    directory.mkdir(parents=True)
    (directory / "a-base.toml").write_text("[simulation]\nname = 'a-base'\n", encoding="utf-8")
    (directory / "a-cal.toml").write_text(
        "[simulation]\nname = 'a-cal'\n\n[calibration]\nparallel = 5\n", encoding="utf-8"
    )
    cases = tuple(
        PlanCase(
            case_id=name, site="a", recipe=name[2:], config_hash="0", config_path=f"{name}.toml"
        )
        for name in ("a-base", "a-cal")
    )
    stored = StoredPlan(directory=directory, plan=None, sites=pa.table({}), cases=cases)  # type: ignore[arg-type]

    planned = {case.case_id: case for case in launch_local.planned_cases(stored)}

    assert (planned["a-base"].workflow, planned["a-base"].solves) == ("simulation", 1)
    assert (planned["a-cal"].workflow, planned["a-cal"].solves) == ("calibration", 5)
    assert planned["a-cal"].rel_path == "plan/abc/a-cal.toml"


def test_the_width_of_a_calibration_is_its_widest_phase() -> None:
    assert calibration_width({}) == 1
    assert calibration_width({"parallel": 5}) == 5
    assert calibration_width({"parallel": 2, "phases": [{"name": "a"}, {"parallel": 40}]}) == 40
    assert calibration_width({"parallel": 8, "phases": [{"parallel": 3}, {"parallel": 2}]}) == 3
    assert calibration_width({"parallel": 4, "phases": [{"parallel": 1}, {"name": "b"}]}) == 4


@pytest.mark.allow_subprocess
def test_a_cache_that_cannot_be_merged_fails_its_case_only(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path)
    write_behaviour(project, {"alpha-k2e_5": {"prepare": "corrupt_cache"}})
    plan_project(project)

    report = run_plan(project)

    outcomes = {case.case_id: case.status for case in report.cases}
    assert outcomes["alpha-k2e_5"] == "failed"
    assert outcomes["beta-base"] == "completed"
    merge_failed = events(report.journal, "merge_failed")
    assert [event["case_id"] for event in merge_failed] == ["alpha-k2e_5"]
    assert Path(merge_failed[0]["private_cache"]).is_file()
    assert events(report.journal, "launch_end")
