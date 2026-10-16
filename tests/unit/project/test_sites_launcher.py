"""The local launcher of a ``[sites]`` project: one process per case, journal, budget, status.

The launcher writes the plan, starts one worker per case in a process of its
own under a budget of solves, writes every event to
``jobs/<stamp>-local/journal.jsonl``, writes ``failed`` for a worker that died
without writing its end, refreshes the index after every end, and reads the
status of each case from the disk alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.config.sites.budget import BudgetError
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.project.launch import local as launch_local
from hydromodpy.project.launch import plan_project, project_status, read_journal, run_plan
from hydromodpy.project.launch.children import PlannedCase
from hydromodpy.project.launch.journal import (
    CASES_FILENAME,
    case_for_task,
    new_job_dir,
    write_case_list,
)
from hydromodpy.project.launch.local import effective_parallel, effective_prepare_parallel
from hydromodpy.results.outcome import read_outcome
from tests.unit.project._launch_fakes import (
    CASES,
    seen,
    write_behaviour,
    write_project,
)

pytestmark = pytest.mark.allow_subprocess


def _events(journal: Path, name: str) -> list[dict]:
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line["event"] == name]


def test_every_case_runs_in_a_process_of_its_own_and_is_journalled(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path, sites_extra="[sites.run]\nparallel = 2\n")
    plan_project(project)

    report = run_plan(project)

    assert report.n_completed == 4 and report.n_failed == 0
    assert sorted(case.case_id for case in report.cases) == sorted(CASES)
    pids = {seen(project, case_id)["pid"] for case_id in CASES}
    assert len(pids) == 4
    assert report.journal.parent.parent == project / "jobs"
    assert report.journal.parent.name.endswith("-local")
    starts = _events(report.journal, "case_start")
    ends = _events(report.journal, "case_end")
    assert sorted(event["case_id"] for event in starts) == sorted(CASES)
    assert {event["status"] for event in ends} == {"completed"}
    assert _events(report.journal, "launch_end")[0]["n_completed"] == 4
    assert not (project / ".hmp" / "launcher.lease").exists()


def test_the_index_is_refreshed_by_the_launcher_after_every_end(
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


def test_a_worker_that_dies_without_its_outcome_is_closed_failed_by_the_launcher(
    tmp_path: Path, fake_worker: Path
) -> None:
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


def test_status_reads_the_disk_and_log_names_each_failed_case_once(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path)
    plan_project(project)
    planned = project_status(project)
    assert {row.status for row in planned.rows} == {"planned"}

    write_behaviour(project, {"beta-k2e_5": {"run": "fail"}})
    run_plan(project)
    status = {row.case_id: row for row in project_status(project).rows}

    assert status["beta-k2e_5"].status == "failed"
    assert status["beta-k2e_5"].error == "SolverError: boom"
    assert status["alpha-base"].status == "completed"
    assert status["alpha-base"].rel_dir == "runs/alpha-base"
    failed = read_journal(project, failed_only=True)
    assert [event["case_id"] for event in failed] == ["beta-k2e_5"]
    assert failed[0]["log_tail"] == ["boom"]


def test_only_failed_starts_the_failed_cases_again_in_place(
    tmp_path: Path, fake_worker: Path
) -> None:
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


def test_a_completed_plan_starts_nothing_and_site_keeps_one_site(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path)
    plan_project(project)

    first = run_plan(project, site="beta")
    again = run_plan(project, site="beta")

    assert sorted(case.case_id for case in first.cases) == ["beta-base", "beta-k2e_5"]
    assert again.cases == ()
    assert {row.status for row in project_status(project).rows if row.site == "alpha"} == {
        "planned"
    }


def test_status_says_stale_plan_once_the_project_files_change(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path)
    plan_project(project)
    sites = project / "sites.csv"
    sites.write_text(sites.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    report = project_status(project)

    assert report.plan_stale
    assert {row.status for row in report.rows} == {"stale_plan"}


def test_on_error_raise_skips_the_cases_left_after_a_failure(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path, sites_extra='[sites.run]\nparallel = 1\non_error = "raise"\n')
    write_behaviour(project, {"alpha-base": {"run": "fail"}})
    plan_project(project)

    report = run_plan(project)

    assert [case.case_id for case in report.cases] == ["alpha-base"]
    skipped = {event["case_id"] for event in _events(report.journal, "case_skipped")}
    assert skipped == {"alpha-k2e_5", "beta-base", "beta-k2e_5"}
    assert {row.case_id: row.status for row in project_status(project).rows}["beta-base"] == (
        "skipped"
    )


def _case(case_id: str, *, workflow: str = "simulation", solves: int = 1) -> PlannedCase:
    return PlannedCase(
        case_id=case_id,
        site=case_id.split("-")[0],
        recipe=case_id.split("-")[1],
        config_hash="0" * 16,
        path=Path(f"/plan/abc/{case_id}.toml"),
        workflow=workflow,  # type: ignore[arg-type]
        solves=solves,
    )


def test_the_budget_of_solves_is_refused_above_the_ceilings_without_force() -> None:
    simulations = [_case("a-base"), _case("b-base")]
    calibration = [_case("a-cal", workflow="calibration", solves=5)]

    assert effective_parallel(16, simulations, threads_per_case=1, force=False, cores=64) == 16
    with pytest.raises(BudgetError, match="above 16"):
        effective_parallel(17, simulations, threads_per_case=1, force=False, cores=64)
    assert effective_parallel(2, calibration, threads_per_case=1, force=False, cores=64) == 2
    with pytest.raises(BudgetError, match="calibration"):
        effective_parallel(3, calibration, threads_per_case=1, force=False, cores=64)
    with pytest.raises(BudgetError, match="cores"):
        effective_parallel(4, simulations, threads_per_case=4, force=False, cores=8)
    assert effective_parallel(17, calibration, threads_per_case=4, force=True, cores=2) == 17


def test_prepare_parallel_is_refused_above_eight_without_force() -> None:
    assert effective_prepare_parallel(8, force=False) == 8
    with pytest.raises(BudgetError, match="above 8"):
        effective_prepare_parallel(9, force=False)
    assert effective_prepare_parallel(9, force=True) == 9


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


def test_until_data_stops_after_the_prepare_phase(tmp_path: Path, fake_worker: Path) -> None:
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


def test_a_task_of_a_job_names_its_case_file(tmp_path: Path) -> None:
    project = tmp_path / "campaign"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")
    job = new_job_dir(project, "slurm")
    write_case_list(job, ["plan/abc/alpha-base.toml", "plan/abc/beta-base.toml"])

    assert (job / CASES_FILENAME).is_file()
    assert case_for_task(project, job.name, 2) == project.resolve() / "plan/abc/beta-base.toml"
    with pytest.raises(IndexError, match="1..2"):
        case_for_task(project, job.name, 3)
