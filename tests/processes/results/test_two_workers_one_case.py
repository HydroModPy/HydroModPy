"""Two workers on one case: one continues, the other stops with a sentence, no ``.v2``.

The claim of an attempt is a ``mkdir`` the kernel serializes: ``runs/<case>``
for a fresh case, ``attempts/<k>`` for a retry. Two real processes race on
the same directory; exactly one wins the claim and writes ``outcome.json`` as
``running``. The loser is refused one of two ways and never mints a version:
it lost the ``mkdir`` ("another worker claimed this case"), or it arrived
once the outcome already said ``running`` with a fresh pulse (the case is
alive). No other verdict exists: a directory the winner created but has not
yet written its outcome into is a claim in flight, refused as claimed.
"""

from __future__ import annotations

import multiprocessing
import os
import socket
import time
from pathlib import Path

import pytest

from hydromodpy.core.state.layout import RUNS_DIRNAME
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import (
    CLAIMED_ELSEWHERE,
    AttemptClaimedError,
    CaseAliveError,
    DirectoryWithoutOutcomeError,
    claim_run_directory,
    finish_dead_attempt,
    latest_version_dir,
)
from hydromodpy.results.storage.contract import RUN_ATTEMPTS_DIRNAME, RUN_OUTCOME_FILENAME
from tests._helpers.sealed_runs import make_project, write_attempt

CASE = "nancon_monthly"
ROUNDS = 5
"""How many times a race is run: a window of a few microseconds needs several tries."""


def _worker(project_root: str, start_at: float, queue) -> None:
    while time.monotonic() < start_at:
        pass
    try:
        claim = claim_run_directory(
            Path(project_root), CASE, case_id=CASE, project="demo", site="nancon"
        )
    except AttemptClaimedError as exc:
        queue.put(("lost", None, str(exc)))
    except CaseAliveError as exc:
        queue.put(("alive", None, str(exc)))
    except BaseException as exc:  # noqa: BLE001 - the test judges every verdict
        queue.put((f"crashed: {type(exc).__name__}", None, str(exc)))
    else:
        queue.put(("won", claim.attempt, claim.attempt_id))


def _race(project_root: Path, workers: int = 2) -> list[tuple[str, int | None, str | None]]:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    start_at = time.monotonic() + 1.0
    processes = [
        context.Process(target=_worker, args=(str(project_root), start_at, queue))
        for _ in range(workers)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=60) for _ in processes]
    for process in processes:
        process.join(timeout=60)
    return results


def _assert_documented_verdicts(results: list[tuple[str, int | None, str | None]]) -> None:
    verdicts = sorted(result[0] for result in results)
    assert verdicts in (["lost", "won"], ["alive", "won"]), results
    loser = next(result for result in results if result[0] != "won")
    if loser[0] == "lost":
        assert loser[2] is not None and loser[2].startswith(CLAIMED_ELSEWHERE), loser


def test_two_workers_on_a_failed_case_one_continues_and_no_version_is_minted(tmp_path):
    project = make_project(tmp_path / "demo")
    write_attempt(project, f"{RUNS_DIRNAME}/{CASE}", status="failed", attempt=1)

    results = _race(project)

    _assert_documented_verdicts(results)
    winner = next(result for result in results if result[0] == "won")
    assert winner[1] == 2

    runs = sorted(entry.name for entry in (project / RUNS_DIRNAME).iterdir())
    assert runs == [CASE], "a retry never mints a version"
    outcome = read_outcome(project / RUNS_DIRNAME / CASE)
    assert outcome is not None
    assert outcome.status == "running"
    assert outcome.attempt == 2
    assert outcome.attempt_id == winner[2]
    archived = project / RUNS_DIRNAME / CASE / RUN_ATTEMPTS_DIRNAME / "1" / RUN_OUTCOME_FILENAME
    assert archived.is_file(), "the outcome of attempt 1 is filed under attempts/1/"
    assert read_outcome(archived.parent).status == "failed"


def test_a_running_case_with_a_fresh_pulse_refuses_every_newcomer(tmp_path):
    project = make_project(tmp_path / "demo")
    write_attempt(
        project, f"{RUNS_DIRNAME}/{CASE}", status="running", attempt=1, heartbeat_age_s=1.0
    )

    results = _race(project)

    assert sorted(result[0] for result in results) == ["alive", "alive"], results
    assert latest_version_dir(project, CASE) == project / RUNS_DIRNAME / CASE
    assert read_outcome(project / RUNS_DIRNAME / CASE).attempt == 1


@pytest.mark.parametrize("round_", range(ROUNDS))
def test_two_workers_on_a_fresh_case_claim_one_directory_only(tmp_path, round_):
    project = make_project(tmp_path / "demo")

    results = _race(project)

    _assert_documented_verdicts(results)
    assert sorted(entry.name for entry in (project / RUNS_DIRNAME).iterdir()) == [CASE]
    outcome = read_outcome(project / RUNS_DIRNAME / CASE)
    assert outcome is not None and outcome.status == "running" and outcome.attempt == 1


def test_a_directory_without_outcome_is_a_claim_in_flight_while_it_is_young(tmp_path):
    project = make_project(tmp_path / "demo")
    (project / RUNS_DIRNAME / CASE).mkdir(parents=True)

    with pytest.raises(AttemptClaimedError, match=CLAIMED_ELSEWHERE):
        claim_run_directory(project, CASE, case_id=CASE, project="demo")


def test_an_old_directory_without_outcome_is_refused_with_what_to_do(tmp_path):
    project = make_project(tmp_path / "demo")
    directory = project / RUNS_DIRNAME / CASE
    directory.mkdir(parents=True)
    old = time.time() - 3600.0
    os.utime(directory, (old, old))

    with pytest.raises(DirectoryWithoutOutcomeError, match="trash it, or rename it"):
        claim_run_directory(project, CASE, case_id=CASE, project="demo")


def test_a_retry_whose_request_changed_starts_fresh(tmp_path):
    from hydromodpy.results.storage.attempt import (
        finish_attempt,
        record_request_id,
        start_over_if_changed,
    )

    project = make_project(tmp_path / "demo")
    run_dir = write_attempt(project, f"{RUNS_DIRNAME}/{CASE}", status="failed", attempt=1)
    record_request_id(run_dir, "a" * 64)
    (run_dir / "fields.zarr").mkdir()

    claim = claim_run_directory(project, CASE, case_id=CASE, project="demo")
    same = start_over_if_changed(claim, "a" * 64)
    assert same.resumed and same.attempt == 2
    assert (run_dir / "fields.zarr").is_dir(), "a resume in place keeps the partial store"
    record_request_id(run_dir, "a" * 64)

    # Attempt 2 is closed as failed, then a third one comes asking for something else.
    finish_attempt(run_dir, status="failed", error=RuntimeError("again"))
    third = claim_run_directory(project, CASE, case_id=CASE, project="demo")
    changed = start_over_if_changed(third, "b" * 64)
    assert not changed.resumed and changed.attempt == 3
    assert not (run_dir / "fields.zarr").exists(), "a changed request moves everything"
    assert (run_dir / RUN_ATTEMPTS_DIRNAME / "2" / "fields.zarr").is_dir()


def test_the_launcher_closes_only_the_worker_it_named(tmp_path):
    """A newcomer refused by the claim never writes the outcome of the worker that holds it."""
    project = make_project(tmp_path / "demo")
    run_dir = write_attempt(
        project,
        f"{RUNS_DIRNAME}/{CASE}",
        status="running",
        attempt=1,
        heartbeat_age_s=1.0,
        host=socket.gethostname(),
        pid=os.getppid(),
    )

    foreign = finish_dead_attempt(run_dir, host=socket.gethostname(), pid=os.getpid(), exit_code=1)
    assert foreign is None
    assert read_outcome(run_dir).status == "running"

    own = finish_dead_attempt(
        run_dir, host=socket.gethostname(), pid=os.getppid(), exit_code=15, signal=None
    )
    assert own is not None and own.status == "failed" and own.written_by == "launcher"
    assert own.exit_code == 15
