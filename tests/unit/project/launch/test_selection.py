"""Which cases the launcher starts, with which flags and under which budget.

A budget of parallel solves (one MODFLOW run each) is refused above the ceilings
unless forced. A calibration is reopened only when its session holds the planned
hash and its worker is proven dead, and never started while a worker may be alive.
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
    sites_run_config,
    worker_flags,
)
from hydromodpy.project.launch.status import CaseState
from hydromodpy.results.outcome import Outcome, write_outcome
from hydromodpy.results.session.descriptor import write_session
from tests._helpers.sealed_runs import manifest_document
from tests._helpers.session_documents import session_descriptor


def planned_case(
    case_id: str = "a-cal",
    *,
    workflow: str = "calibration",
    solves: int = 1,
    config_hash: str = "h1",
    folder: Path = Path("/plan/abc"),
) -> PlannedCase:
    site, recipe = case_id.split("-")
    return PlannedCase(
        case_id=case_id,
        site=site,
        recipe=recipe,
        config_hash=config_hash,
        path=folder / f"{case_id}.toml",
        workflow=workflow,  # type: ignore[arg-type]
        solves=solves,
    )


def running_outcome(case_id: str, now: datetime, *, host: str, pid: int) -> Outcome:
    return Outcome(
        case_id=case_id,
        attempt=1,
        attempt_id="a1",
        status="running",
        written_by="worker",
        started_at=now,
        host=host,
        pid=pid,
    )


SIMULATIONS = [
    planned_case("a-base", workflow="simulation"),
    planned_case("b-base", workflow="simulation"),
]
CALIBRATION = [planned_case(solves=2)]
WIDE_5 = [planned_case(solves=5)]
WIDE_40 = [planned_case(solves=40)]

# (parallel asked, cases, threads per case, cores of the machine, result)
ACCEPTED_PARALLEL = [
    pytest.param(16, SIMULATIONS, 1, 64, False, 16, id="simulations at the ceiling"),
    pytest.param(8, CALIBRATION, 1, 64, False, 8, id="calibration at the ceiling"),
    pytest.param(17, CALIBRATION, 4, 2, True, 17, id="forced above every ceiling"),
    pytest.param(2, WIDE_40, 1, 64, True, 2, id="forced wide calibration"),
]


@pytest.mark.parametrize(
    ("asked", "cases", "threads", "cores", "force", "result"), ACCEPTED_PARALLEL
)
def test_accepted_parallel(asked, cases, threads, cores, force, result):
    assert (
        effective_parallel(asked, cases, threads_per_case=threads, force=force, cores=cores)
        == result
    )


# (parallel asked, cases, threads per case, cores of the machine, message)
REFUSED_PARALLEL = [
    pytest.param(17, SIMULATIONS, 1, 64, "above 16", id="simulations above 16"),
    pytest.param(
        2, WIDE_5, 1, 64, "parallel = 5 of case a-cal exceeds", id="calibration wider than asked"
    ),
    pytest.param(9, CALIBRATION, 1, 64, "measured ceiling is 8", id="calibration above 8"),
    pytest.param(4, SIMULATIONS, 4, 8, "cores", id="more threads than cores"),
    pytest.param(
        2,
        WIDE_40,
        1,
        64,
        r"parallel = 40 of case a-cal exceeds .* = 2",
        id="calibration of 40 solves",
    ),
    pytest.param(40, WIDE_40, 1, 64, "above 16", id="forty asked without force"),
]


@pytest.mark.parametrize(("asked", "cases", "threads", "cores", "message"), REFUSED_PARALLEL)
def test_parallel_refusals(asked, cases, threads, cores, message):
    with pytest.raises(BudgetError, match=message):
        effective_parallel(asked, cases, threads_per_case=threads, force=False, cores=cores)


def test_prepare_parallel_ceiling():
    assert effective_prepare_parallel(8, force=False) == 8
    with pytest.raises(BudgetError, match="above 8"):
        effective_prepare_parallel(9, force=False)
    assert effective_prepare_parallel(9, force=True) == 9


def test_folder_without_marker_refused(tmp_path):
    with pytest.raises(ConfigError, match="not a project"):
        sites_run_config(tmp_path)


def failed_state(session_hash: str = "h1") -> CaseState:
    return CaseState("failed", "sessions/a-cal", None, session_hash=session_hash)


def stale_state(host: str, pid: int) -> CaseState:
    outcome = {"status": "running", "host": host, "pid": pid}
    return CaseState("stale", "sessions/a-cal", outcome, session_hash="h1")


DEAD_HERE = stale_state(socket.gethostname(), 2**22 + 7)
ELSEWHERE = stale_state("node12", 1)

# (state of the case, frozen, fresh, force, flags of the worker)
WORKER_FLAGS = [
    pytest.param(failed_state(), False, False, False, ["--resume"], id="failed with planned hash"),
    pytest.param(failed_state(), True, False, False, ["--frozen", "--resume"], id="frozen resume"),
    pytest.param(failed_state(), False, True, False, [], id="fresh start asked"),
    pytest.param(failed_state("h0"), False, False, False, [], id="session of another hash"),
    pytest.param(CaseState("planned"), False, False, False, [], id="no session yet"),
    pytest.param(ELSEWHERE, False, False, False, [], id="stale on another host"),
    pytest.param(ELSEWHERE, False, False, True, ["--resume"], id="stale on another host forced"),
    pytest.param(DEAD_HERE, False, False, False, ["--resume"], id="worker dead on this host"),
]


@pytest.mark.parametrize(("state", "frozen", "fresh", "force", "flags"), WORKER_FLAGS)
def test_worker_flags(state, frozen, fresh, force, flags):
    case = planned_case()

    assert worker_flags(case, state, frozen=frozen, fresh=fresh, force=force) == flags


def test_live_session_not_restarted(tmp_path):
    project = tmp_path / "campaign"
    session = project / "sessions" / "a-cal"
    session.mkdir(parents=True)
    now = datetime.now(UTC)
    write_session(
        session, session_descriptor("a-cal", session_id="s1", config_hash="h1", started_at=now)
    )
    write_outcome(
        session, running_outcome("a-cal", now, host=socket.gethostname(), pid=os.getpid())
    )

    chosen, left = select_cases(project, [planned_case()], only=("a-cal",))

    assert chosen == []
    assert [(case.case_id, why) for case, why in left] == [("a-cal", "running")]


def test_changed_calibration_restarts(tmp_path):
    project = tmp_path / "campaign"
    case = planned_case(
        "nancon-calibration", config_hash="new-plan-hash", folder=project / "plan" / "abc"
    )
    now = datetime.now(UTC)
    write_session(
        sessions_dir_for(project) / case.case_id,
        session_descriptor(
            case.case_id,
            session_id="s1",
            config_hash="old-plan-hash",
            status="completed",
            started_at=now,
            ended_at=now,
        ),
    )
    run_dir = runs_dir_for(project) / case.case_id
    run_dir.mkdir(parents=True)
    document = manifest_document(name=case.case_id, config_hash="promoted-hash")
    (run_dir / "manifest.json").write_text(json.dumps(document), encoding="utf-8")

    chosen, _ = select_cases(project, [case])

    assert [planned.case_id for planned, _ in chosen] == ["nancon-calibration"]
