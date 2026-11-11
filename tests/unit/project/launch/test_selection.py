"""Which cases the launcher starts, with which flags and under which budget.

The budget of solves is refused above the ceilings without ``--force``; a
calibration is done once a session holds the hash of the plan, reopened only
when the death of its worker is proven, and never started again while a live
worker may hold it.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.layout import runs_dir_for, sessions_dir_for
from hydromodpy.project.launch.children import PlannedCase
from hydromodpy.project.launch.plan import BudgetError
from hydromodpy.project.launch.selection import (
    effective_parallel,
    effective_prepare_parallel,
    select_cases,
    worker_flags,
)
from hydromodpy.project.launch.status import CaseState
from hydromodpy.results.outcome import Outcome, write_outcome
from hydromodpy.results.session.descriptor import write_session
from tests._helpers.sealed_runs import manifest_document
from tests._helpers.session_documents import session_descriptor


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
    calibration = [_case("a-cal", workflow="calibration", solves=2)]
    wide = [_case("a-cal", workflow="calibration", solves=5)]

    assert effective_parallel(16, simulations, threads_per_case=1, force=False, cores=64) == 16
    with pytest.raises(BudgetError, match="above 16"):
        effective_parallel(17, simulations, threads_per_case=1, force=False, cores=64)
    assert effective_parallel(8, calibration, threads_per_case=1, force=False, cores=64) == 8
    with pytest.raises(BudgetError, match="parallel = 5 of case a-cal exceeds"):
        effective_parallel(2, wide, threads_per_case=1, force=False, cores=64)
    with pytest.raises(BudgetError, match="measured ceiling is 8"):
        effective_parallel(9, calibration, threads_per_case=1, force=False, cores=64)
    with pytest.raises(BudgetError, match="cores"):
        effective_parallel(4, simulations, threads_per_case=4, force=False, cores=8)
    assert effective_parallel(17, calibration, threads_per_case=4, force=True, cores=2) == 17


def test_prepare_parallel_is_refused_above_eight_without_force() -> None:
    assert effective_prepare_parallel(8, force=False) == 8
    with pytest.raises(BudgetError, match="above 8"):
        effective_prepare_parallel(9, force=False)
    assert effective_prepare_parallel(9, force=True) == 9


def test_a_folder_without_the_marker_is_no_project_for_the_run_section(tmp_path: Path) -> None:
    from hydromodpy.project.launch.selection import sites_run_config

    with pytest.raises(ConfigError, match="not a project"):
        sites_run_config(tmp_path)


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


def _write_session(project: Path, case_id: str, config_hash: str) -> None:
    now = datetime.now(UTC)
    write_session(
        sessions_dir_for(project) / case_id,
        session_descriptor(
            case_id,
            session_id="s1",
            config_hash=config_hash,
            status="completed",
            started_at=now,
            ended_at=now,
        ),
    )


def _promoted_run(project: Path, case_id: str, config_hash: str) -> None:
    run_dir = runs_dir_for(project) / case_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest_document(name=case_id, config_hash=config_hash)), encoding="utf-8"
    )


def _calibration_case(project: Path, case_id: str, config_hash: str) -> PlannedCase:
    return PlannedCase(
        case_id=case_id,
        site=case_id.split("-")[0],
        recipe=case_id.split("-")[1],
        config_hash=config_hash,
        path=project / "plan" / "abc" / f"{case_id}.toml",
        workflow="calibration",
        solves=1,
    )


def test_a_finished_calibration_is_not_started_again(tmp_path: Path) -> None:
    project = tmp_path / "campaign"
    case = _calibration_case(project, "nancon-calibration", "plan-hash")
    _write_session(project, case.case_id, "plan-hash")
    # The promoted run carries the K of the best trial: another hash.
    _promoted_run(project, case.case_id, "promoted-hash")

    chosen, _ = select_cases(project, [case])

    assert chosen == []


def test_a_calibration_whose_files_changed_is_started_again(tmp_path: Path) -> None:
    project = tmp_path / "campaign"
    case = _calibration_case(project, "nancon-calibration", "new-plan-hash")
    _write_session(project, case.case_id, "old-plan-hash")
    _promoted_run(project, case.case_id, "promoted-hash")

    chosen, _ = select_cases(project, [case])

    assert [planned.case_id for planned, _ in chosen] == ["nancon-calibration"]
