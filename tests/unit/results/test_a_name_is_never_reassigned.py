"""A deleted run name is never given to a new run, whether its bytes are freed or not.

A version is given by the disk at the reservation, never written by hand. A
name that carries ``.vN`` reaches only its live directory; the trash, a
tombstone or a void does not hand it out again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.state.paths import RUNS_DIRNAME
from hydromodpy.results.catalog.registration import NameTakenError, reserve_version_dirname
from hydromodpy.results.storage.attempt import (
    RunClaim,
    claim_run_directory,
    close_sealed_attempt,
    finish_attempt,
)
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import gc_trash, list_trash, read_tombstones, trash_run
from hydromodpy.simulation.planning.config import SimulationConfig
from tests._helpers.run_stores import claim_run, open_run_store

AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def _live_runs(project) -> list[str]:
    return sorted(entry.name for entry in (project / RUNS_DIRNAME).iterdir())


def test_a_trashed_then_collected_version_is_not_reassigned(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    second = reserve_version_dirname(tmp_path, "run", "nancon")
    assert second.name == "nancon.v2"

    trash_run(tmp_path, "runs/nancon.v2", now=AT)
    freed = gc_trash(tmp_path, older_than=timedelta(0), now=AT + timedelta(days=31))

    assert [tombstone.rel_dir for tombstone in freed] == ["runs/nancon.v2"]
    assert list_trash(tmp_path) == []
    assert _live_runs(tmp_path) == ["nancon"]
    assert [t.rel_dir for t in read_tombstones(tmp_path)] == ["runs/nancon.v2"]

    third = reserve_version_dirname(tmp_path, "run", "nancon")

    assert third.name == "nancon.v3"


def test_a_trashed_version_is_not_reassigned_before_the_gc(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    reserve_version_dirname(tmp_path, "run", "nancon")

    trash_run(tmp_path, "runs/nancon.v2", now=AT)
    assert _live_runs(tmp_path) == ["nancon"]

    third = reserve_version_dirname(tmp_path, "run", "nancon")

    assert third.name == "nancon.v3"


def test_the_bare_name_once_collected_is_not_reassigned(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    trash_run(tmp_path, "runs/nancon", now=AT)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT)

    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v2"


def _claim(project: Path, name: str, **kwargs: object) -> RunClaim:
    return claim_run_directory(project, name, case_id=name, project=project.name, **kwargs)


def _sealed(project: Path, name: str) -> Path:
    store = open_run_store(project, name, create_zarr=False)
    seal_completed(store)
    close_sealed_attempt(store.run_dir)
    return store.run_dir


def test_a_versioned_name_the_trash_holds_is_refused(tmp_path):
    _sealed(tmp_path, "a")
    assert _sealed(tmp_path, "a").name == "a.v2"
    trash_run(tmp_path, "runs/a.v2", now=AT)
    assert [entry.rel_dir for entry in list_trash(tmp_path)] == ["runs/a.v2"]

    with pytest.raises(NameTakenError, match=r"trash:runs/a\.v2.*name the case 'a'"):
        _claim(tmp_path, "a.v2")

    assert _live_runs(tmp_path) == ["a"]


def test_a_versioned_name_a_tombstone_holds_is_refused(tmp_path):
    _sealed(tmp_path, "nancon")
    _sealed(tmp_path, "nancon")
    trash_run(tmp_path, "runs/nancon", now=AT)
    trash_run(tmp_path, "runs/nancon.v2", now=AT)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT)
    assert "runs/nancon.v2" in [t.rel_dir for t in read_tombstones(tmp_path)]

    with pytest.raises(NameTakenError, match=r"tombstone:runs/nancon\.v2.*'nancon'"):
        _claim(tmp_path, "nancon.v2")

    assert _live_runs(tmp_path) == []


def test_a_versioned_name_nobody_holds_is_refused(tmp_path):
    (tmp_path / RUNS_DIRNAME).mkdir()

    with pytest.raises(NameTakenError, match="name the case 'fresh'"):
        _claim(tmp_path, "fresh.v2")

    assert _live_runs(tmp_path) == []


def test_a_versioned_name_retries_its_own_unfinished_directory(tmp_path):
    _sealed(tmp_path, "a")
    second = claim_run(tmp_path, "a")
    finish_attempt(second.run_dir, status="failed", exit_code=1)

    retry = _claim(tmp_path, "a.v2")

    assert retry.run_dir == second.run_dir
    assert retry.attempt == 2


def test_a_completed_versioned_name_takes_the_next_version_of_its_stem(tmp_path):
    _sealed(tmp_path, "a")
    _sealed(tmp_path, "a")
    _sealed(tmp_path, "a")
    trash_run(tmp_path, "runs/a.v3", now=AT)

    assert _claim(tmp_path, "a.v2").name == "a.v4"


def test_a_simulation_name_never_carries_its_version():
    with pytest.raises(ValidationError, match="write name = 'a'"):
        SimulationConfig(name="a.v2")

    assert SimulationConfig(name="a.vintage").name == "a.vintage"
