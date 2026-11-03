"""A calibration case of a ``[sites]`` campaign holds the rules of the launcher.

A calibration case is its session ``sessions/<case>/`` until it promotes. The
launcher closes the session of a worker that died, so the case reads
``failed`` and starts again; it reopens that session instead of making a
``.v2``; it counts the widest phase of the case in the budget of solves and
refuses a case wider than the budget; and it never starts again a session a
live worker may hold.
"""

from __future__ import annotations

import os
import socket
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.config.sites.budget import BudgetError
from hydromodpy.project.launch import local as launch_local
from hydromodpy.project.launch import plan_project, run_plan
from hydromodpy.project.launch.children import PlannedCase, calibration_width
from hydromodpy.project.launch.local import effective_parallel, select_cases, worker_flags
from hydromodpy.project.launch.status import CaseState, case_state
from hydromodpy.results.outcome import Outcome, read_outcome, write_outcome
from hydromodpy.results.session.descriptor import read_session, write_session
from tests._helpers.session_documents import session_descriptor
from tests.unit.project._launch_fakes import seen, write_behaviour, write_project

pytestmark = pytest.mark.allow_subprocess

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


def test_a_dead_calibration_worker_leaves_a_failed_session_that_starts_again(
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
    chosen, _ = select_cases(project, launch_local.planned_cases(_stored(project)))
    assert calibration_case in {case.case_id for case, _ in chosen}
    chosen, _ = select_cases(
        project, launch_local.planned_cases(_stored(project)), only=("failed",)
    )
    assert [case.case_id for case, _ in chosen] == [calibration_case]


def test_a_failed_calibration_reopens_its_session_and_fresh_opens_a_new_one(
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


def _stored(project: Path):
    from hydromodpy.results.plan_store import read_plan

    return read_plan(project)


def _calibration(case_id: str = "a-cal", *, solves: int = 1, config_hash: str = "h1"):
    return PlannedCase(
        case_id=case_id,
        site="a",
        recipe="cal",
        config_hash=config_hash,
        path=Path(f"/plan/abc/{case_id}.toml"),
        workflow="calibration",
        solves=solves,
    )


def _outcome(*, host: str, pid: int) -> dict:
    return {"status": "running", "host": host, "pid": pid}


def test_only_a_session_of_the_planned_hash_is_reopened() -> None:
    case = _calibration()
    failed = CaseState("failed", "sessions/a-cal", None, session_hash="h1")

    assert worker_flags(case, failed, frozen=False, fresh=False, force=False) == ["--resume"]
    assert worker_flags(case, failed, frozen=True, fresh=False, force=False) == [
        "--frozen",
        "--resume",
    ]
    assert worker_flags(case, failed, frozen=False, fresh=True, force=False) == []
    changed = CaseState("failed", "sessions/a-cal", None, session_hash="h0")
    assert worker_flags(case, changed, frozen=False, fresh=False, force=False) == []
    planned = CaseState("planned")
    assert worker_flags(case, planned, frozen=False, fresh=False, force=False) == []


def test_a_stale_session_is_reopened_only_when_its_death_is_proven_or_forced(
    tmp_path: Path,
) -> None:
    case = _calibration()
    elsewhere = CaseState(
        "stale", "sessions/a-cal", _outcome(host="node12", pid=1), session_hash="h1"
    )
    dead_here = CaseState(
        "stale",
        "sessions/a-cal",
        _outcome(host=socket.gethostname(), pid=2**22 + 7),
        session_hash="h1",
    )

    assert worker_flags(case, elsewhere, frozen=False, fresh=False, force=False) == []
    assert worker_flags(case, elsewhere, frozen=False, fresh=False, force=True) == ["--resume"]
    assert worker_flags(case, dead_here, frozen=False, fresh=False, force=False) == ["--resume"]


def test_a_session_a_live_worker_may_hold_is_never_started_again(tmp_path: Path) -> None:
    project = tmp_path / "campaign"
    session = project / "sessions" / "a-cal"
    session.mkdir(parents=True)
    now = datetime.now(UTC)
    write_session(
        session,
        session_descriptor("a-cal", session_id="s1", config_hash="h1", started_at=now),
    )
    write_outcome(
        session,
        Outcome(
            case_id="a-cal",
            attempt=1,
            attempt_id="a1",
            status="running",
            written_by="worker",
            started_at=now,
            host=socket.gethostname(),
            pid=os.getpid(),
        ),
    )
    case = _calibration()

    chosen, left = select_cases(project, [case], only=("a-cal",))

    assert chosen == [] and [(c.case_id, why) for c, why in left] == [("a-cal", "running")]


def test_a_calibration_wider_than_the_budget_is_refused_without_force() -> None:
    wide = [_calibration(solves=40)]

    with pytest.raises(BudgetError, match=r"parallel = 40 of case a-cal exceeds .* = 2"):
        effective_parallel(2, wide, threads_per_case=1, force=False, cores=64)
    assert effective_parallel(2, wide, threads_per_case=1, force=True, cores=64) == 2
    with pytest.raises(BudgetError, match="above 16"):
        effective_parallel(40, wide, threads_per_case=1, force=False, cores=64)


def test_the_width_of_a_calibration_is_its_widest_phase() -> None:
    assert calibration_width({}) == 1
    assert calibration_width({"parallel": 5}) == 5
    assert calibration_width({"parallel": 2, "phases": [{"name": "a"}, {"parallel": 40}]}) == 40
    assert calibration_width({"parallel": 8, "phases": [{"parallel": 3}, {"parallel": 2}]}) == 3
    assert calibration_width({"parallel": 4, "phases": [{"parallel": 1}, {"name": "b"}]}) == 4
