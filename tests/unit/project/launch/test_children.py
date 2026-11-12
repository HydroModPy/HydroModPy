"""The case processes of the launcher and what they leave behind.

A calibration case is as wide as its widest phase, and a plan gives its cases
their workflow and their solves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hydromodpy.project.launch import local as launch_local
from hydromodpy.project.launch.children import calibration_width


def test_a_calibration_counts_its_own_parallel_in_the_budget(tmp_path: Path) -> None:
    import pandas as pd

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
    stored = StoredPlan(directory=directory, plan=None, sites=pd.DataFrame(), cases=cases)  # type: ignore[arg-type]

    planned = {case.case_id: case for case in launch_local.planned_cases(stored)}

    assert (planned["a-base"].workflow, planned["a-base"].solves) == ("simulation", 1)
    assert (planned["a-cal"].workflow, planned["a-cal"].solves) == ("calibration", 5)
    assert planned["a-cal"].rel_path == "plan/abc/a-cal.toml"


WIDTHS = [
    pytest.param({}, 1, id="no parallel"),
    pytest.param({"parallel": 5}, 5, id="flat"),
    pytest.param(
        {"parallel": 2, "phases": [{"name": "a"}, {"parallel": 40}]}, 40, id="widest phase"
    ),
    pytest.param({"parallel": 8, "phases": [{"parallel": 3}, {"parallel": 2}]}, 3, id="phases win"),
    pytest.param(
        {"parallel": 4, "phases": [{"parallel": 1}, {"name": "b"}]}, 4, id="phase without it"
    ),
]


@pytest.mark.parametrize(("calibration", "width"), WIDTHS)
def test_width_of_a_calibration(calibration, width) -> None:
    assert calibration_width(calibration) == width


def test_the_command_line_of_a_case_carries_the_environment_flags() -> None:
    from hydromodpy.project.launch.children import PlannedCase, worker_command

    case = PlannedCase(
        case_id="cal",
        site="a",
        recipe="base",
        config_hash="0",
        path=Path("plan/ab/cal.toml"),
        workflow="simulation",
        solves=1,
    )

    command = worker_command(
        case,
        ["--frozen"],
        environment_flags=("--credentials", "c.toml", "--allow-host", "h.org"),
    )

    assert command[:5] == [sys.executable, "-m", "hydromodpy", "run", str(Path("plan/ab/cal.toml"))]
    assert command[5:] == [
        "--frozen",
        "--credentials",
        "c.toml",
        "--allow-host",
        "h.org",
    ]
