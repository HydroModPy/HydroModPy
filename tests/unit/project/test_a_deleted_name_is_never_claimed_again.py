"""The claim of a run never hands out a name the trash or a tombstone holds.

A run deleted to the trash keeps its name: the next run of the case takes the
next version. ``[simulation] if_exists = "fail"`` takes no new name at all
when any version of the case is held, live or deleted, and leaves nothing on
disk. A retry of an unfinished attempt reuses its own directory and gives out
no name, so ``fail`` lets it through.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.results.catalog.registration import NameTakenError
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import (
    claim_run_directory,
    close_sealed_attempt,
    finish_attempt,
)
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import trash_run
from tests._helpers.run_stores import claim_run, open_run_store


def _sealed(project: Path, name: str) -> Path:
    store = open_run_store(project, name, create_zarr=False)
    run_dir = store.run_dir
    seal_completed(store)
    close_sealed_attempt(run_dir)
    return run_dir


def _claim(project: Path, name: str, **kwargs: object):
    return claim_run_directory(project, name, case_id=name, project=project.name, **kwargs)


def test_a_trashed_name_gives_the_next_version(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _sealed(project, "alpha")
    trash_run(project, "runs/alpha", now=datetime.now(UTC))

    claim = _claim(project, "alpha")

    assert claim.name == "alpha.v2"
    assert not (project / "runs" / "alpha").exists()


def test_fail_refuses_a_name_the_trash_holds_and_writes_nothing(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _sealed(project, "alpha")
    trash_run(project, "runs/alpha", now=datetime.now(UTC))

    with pytest.raises(NameTakenError, match="trash:runs/alpha"):
        _claim(project, "alpha", if_exists="fail")

    assert sorted(p.name for p in (project / "runs").iterdir()) == []


def test_fail_refuses_a_completed_name(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _sealed(project, "alpha")

    with pytest.raises(NameTakenError, match="runs/alpha"):
        _claim(project, "alpha", if_exists="fail")

    assert sorted(p.name for p in (project / "runs").iterdir()) == ["alpha"]


def test_fail_takes_a_name_nobody_holds(tmp_path: Path) -> None:
    project = tmp_path / "p"
    (project / "runs").mkdir(parents=True)

    assert _claim(project, "beta", if_exists="fail").name == "beta"


def test_fail_lets_an_unfinished_attempt_retry_in_its_directory(tmp_path: Path) -> None:
    project = tmp_path / "p"
    first = claim_run(project, "alpha")
    finish_attempt(first.run_dir, status="failed", exit_code=1)

    retry = _claim(project, "alpha", if_exists="fail")

    assert retry.run_dir == first.run_dir
    assert retry.attempt == 2
    outcome = read_outcome(first.run_dir)
    assert outcome is not None and outcome.status == "running"
