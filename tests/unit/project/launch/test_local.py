"""The local launcher of a ``[sites]`` project: one process per case, journal, budget.

The launcher writes the plan, starts one worker per case in a process of its
own under a budget of solves, writes every event to
``jobs/<stamp>-local/journal.jsonl``, writes ``failed`` for a worker that died
without writing its end, refreshes the index after every end, stops after the
prepare phase when asked, and restarts a failed calibration in its own session.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.project.launch import local as launch_local
from hydromodpy.project.launch.local import plan_project, run_plan
from hydromodpy.project.launch.selection import select_cases
from hydromodpy.project.launch.status import case_state, project_status
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.plan_store import read_plan
from hydromodpy.results.session.descriptor import read_session
from tests.unit.project.launch._launch_fakes import (
    CASES,
    events,
    seen,
    write_behaviour,
    write_project,
)

pytestmark = pytest.mark.allow_subprocess


def test_one_process_per_case(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path, sites_extra="[sites.run]\nparallel = 2\n")
    plan_project(project)

    report = run_plan(project)

    assert report.n_completed == 4 and report.n_failed == 0
    assert sorted(case.case_id for case in report.cases) == sorted(CASES)
    pids = {seen(project, case_id)["pid"] for case_id in CASES}
    assert len(pids) == 4
    assert report.journal.parent.parent == project / "jobs"
    assert report.journal.parent.name.endswith("-local")
    starts = events(report.journal, "case_start")
    ends = events(report.journal, "case_end")
    assert sorted(event["case_id"] for event in starts) == sorted(CASES)
    assert {event["status"] for event in ends} == {"completed"}
    assert events(report.journal, "launch_end")[0]["n_completed"] == 4
    assert not (project / ".hmp" / "launcher.lease").exists()


def test_index_refreshed_after_each_end(
    tmp_path: Path, fake_worker: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = write_project(tmp_path)
    plan_project(project)
    calls: list[Path] = []
    monkeypatch.setattr(
        "hydromodpy.results.catalog.indexer.index_new_runs",
        lambda root, **_: calls.append(Path(root)),
    )

    run_plan(project)

    assert calls == [project.resolve()] * 4
    assert {seen(project, case_id)["env"]["HMP_LAUNCHED_CASE"] for case_id in CASES} == {"local"}


def test_dead_worker_is_closed_failed(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path)
    write_behaviour(project, {"alpha-base": {"run": "die"}, "beta-base": {"run": "fail"}})
    plan_project(project)

    report = run_plan(project)

    by_case = {case.case_id: case for case in report.cases}
    assert by_case["alpha-base"].status == "failed"
    assert by_case["alpha-base"].signal is None and by_case["alpha-base"].exit_code == 9
    outcome = read_outcome(project / "runs" / "alpha-base")
    assert outcome is not None
    assert outcome.status == "failed" and outcome.written_by == "launcher"
    assert outcome.exit_code == 9
    worker_written = read_outcome(project / "runs" / "beta-base")
    assert worker_written is not None and worker_written.written_by == "worker"
    assert report.n_failed == 2 and report.n_completed == 2


def test_only_failed_reruns_in_place(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path)
    write_behaviour(project, {"alpha-k2e_5": {"run": "fail"}})
    plan_project(project)
    run_plan(project)
    write_behaviour(project, {})

    second = run_plan(project, only=("failed",))

    assert [case.case_id for case in second.cases] == ["alpha-k2e_5"]
    assert second.cases[0].status == "completed"
    flags = seen(project, "alpha-k2e_5")["flags"]
    assert flags[flags.index("--resume") + 1] == "alpha-k2e_5"


def test_completed_plan_starts_nothing(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path)
    plan_project(project)

    first = run_plan(project, site="beta")
    again = run_plan(project, site="beta")

    assert sorted(case.case_id for case in first.cases) == ["beta-base", "beta-k2e_5"]
    assert again.cases == ()
    assert {row.status for row in project_status(project).rows if row.site == "alpha"} == {
        "planned"
    }


def test_on_error_raise_skips_the_rest(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path, sites_extra='[sites.run]\nparallel = 1\non_error = "raise"\n')
    write_behaviour(project, {"alpha-base": {"run": "fail"}})
    plan_project(project)

    report = run_plan(project)

    assert [case.case_id for case in report.cases] == ["alpha-base"]
    skipped = {event["case_id"] for event in events(report.journal, "case_skipped")}
    assert skipped == {"alpha-k2e_5", "beta-base", "beta-k2e_5"}
    assert {row.case_id: row.status for row in project_status(project).rows}["beta-base"] == (
        "skipped"
    )


def test_until_data_stops_after_prepare(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path)
    plan_project(project)

    report = run_plan(project, until="data")

    assert report.cases == ()
    assert not (project / "runs").exists()
    assert sorted(path.name for path in (project / "seen").iterdir()) == sorted(
        f"{case_id}.prepare.json" for case_id in CASES
    )
    with pytest.raises(ConfigError, match="prepare phase"):
        run_plan(project, until="build_mesh")


def test_until_data_names_prepared_cases(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path)
    plan_project(project)

    # 50 solves would be refused for a launch that solves.
    report = run_plan(project, until="data", parallel=50)

    assert report.until == "data"
    assert sorted(report.prepared) == sorted(CASES)
    assert report.cases == ()
    assert not runs_dir_for(project).exists()


def test_refused_case_is_failed(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path)
    write_behaviour(project, {"beta-k2e_5": {"run": "refuse"}})
    plan_project(project)

    run_plan(project)

    status = {row.case_id: row.status for row in project_status(project).rows}
    assert status["beta-k2e_5"] == "failed"
    assert status["alpha-base"] == "completed"


CALIBRATED = "alpha-base"


@pytest.fixture
def calibration_case(monkeypatch: pytest.MonkeyPatch) -> str:
    """Make the launcher read ``alpha-base`` as a calibration case of the plan."""
    planned = launch_local.planned_cases

    def as_calibration(stored):
        return [
            replace(case, workflow="calibration") if case.case_id == CALIBRATED else case
            for case in planned(stored)
        ]

    monkeypatch.setattr(launch_local, "planned_cases", as_calibration)
    return CALIBRATED


def _sessions(project: Path) -> list[str]:
    return sorted(entry.name for entry in (project / "sessions").iterdir())


def test_dead_calibration_leaves_failed_session(
    tmp_path: Path, fake_worker: Path, calibration_case: str
) -> None:
    project = write_project(tmp_path, sites_extra="[sites.run]\nparallel = 2\n")
    write_behaviour(project, {calibration_case: {"run": "session_die"}})
    plan_project(project)

    report = run_plan(project)

    session = project / "sessions" / calibration_case
    descriptor = read_session(session)
    assert descriptor.status == "failed" and descriptor.ended_at is not None
    assert "worker ended without writing its outcome" in (descriptor.error_message or "")
    outcome = read_outcome(session)
    assert outcome is not None
    assert (outcome.status, outcome.written_by, outcome.exit_code) == ("failed", "launcher", 9)
    assert case_state(project, calibration_case).status == "failed"
    by_case = {case.case_id: case for case in report.cases}
    assert by_case[calibration_case].status == "failed"
    # Started again by default and by --only failed.
    chosen, _ = select_cases(project, launch_local.planned_cases(read_plan(project)))
    assert calibration_case in {case.case_id for case, _ in chosen}
    chosen, _ = select_cases(
        project, launch_local.planned_cases(read_plan(project)), only=("failed",)
    )
    assert [case.case_id for case, _ in chosen] == [calibration_case]


def test_failed_calibration_reopens_or_starts_fresh(
    tmp_path: Path, fake_worker: Path, calibration_case: str
) -> None:
    project = write_project(tmp_path, sites_extra="[sites.run]\nparallel = 2\n")
    write_behaviour(project, {calibration_case: {"run": "session_die"}})
    plan_project(project)
    run_plan(project)
    assert case_state(project, calibration_case).status == "failed"

    write_behaviour(project, {calibration_case: {"run": "session_complete"}})
    run_plan(project, only=("failed",))

    assert "--resume" in seen(project, calibration_case)["flags"]
    assert _sessions(project) == [calibration_case]
    assert read_session(project / "sessions" / calibration_case).status == "completed"

    write_behaviour(project, {calibration_case: {"run": "session_die"}})
    run_plan(project, only=(calibration_case,), fresh=True)
    assert "--resume" not in seen(project, calibration_case)["flags"]
    assert _sessions(project) == [calibration_case, f"{calibration_case}.v2"]
