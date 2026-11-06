"""Tests of catalog names."""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.cli.helpers import EXIT_AMBIGUOUS_REFERENCE, EXIT_NOT_FOUND
from hydromodpy.core.state.layout import RUNS_DIRNAME
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.discovery import (
    SimulationNotFoundError,
    resolve_rel_dir,
    resolve_trashed,
)
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.catalog.registration import NameTakenError, reserve_version_dirname
from hydromodpy.results.errors import RunNotFoundError
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.run import Run
from hydromodpy.results.storage.attempt import (
    RunClaim,
    claim_run_directory,
    close_sealed_attempt,
    finish_attempt,
)
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import gc_trash, list_trash, read_tombstones, restore, trash_run
from hydromodpy.simulation.planning.config import SimulationConfig
from tests._helpers.run_stores import claim_run, open_run_store
from tests._helpers.sealed_runs import make_project, seal_run

# The trash is a directory of its own: a trashed run leaves ``runs/`` and its
# name answers nothing there any more. Reading it back goes through the trash
# listing, and ``restore`` is the only way out.
AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def _run(project: Path, name: str) -> None:
    (project / "runs" / name).mkdir(parents=True)


def test_a_trashed_name_answers_nothing_in_the_tree(tmp_path: Path) -> None:
    _run(tmp_path, "x")
    trash_run(tmp_path, "runs/x", now=AT)
    with pytest.raises(SimulationNotFoundError):
        resolve_rel_dir(tmp_path, "x")


def test_a_bare_name_never_slides_to_another_version(tmp_path: Path) -> None:
    _run(tmp_path, "x")
    _run(tmp_path, "x.v2")
    trash_run(tmp_path, "runs/x", now=AT)
    with pytest.raises(SimulationNotFoundError):
        resolve_rel_dir(tmp_path, "x")
    assert resolve_rel_dir(tmp_path, "x.v2") == "runs/x.v2"


def test_the_trash_listing_is_what_restore_reads(tmp_path: Path) -> None:
    _run(tmp_path, "x")
    trash_run(tmp_path, "runs/x", now=AT)
    entry = resolve_trashed(tmp_path, "x")
    restore(tmp_path, entry.name)
    assert resolve_rel_dir(tmp_path, "x") == "runs/x"


# A run deleted to the trash keeps its name: the next run of the case takes the
# next version. ``[simulation] if_exists = "fail"`` takes no new name at all
# when any version of the case is held, live or deleted, and leaves nothing on
# disk. A retry of an unfinished attempt reuses its own directory and gives out
# no name, so ``fail`` lets it through.
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


# A version is given by the disk at the reservation, never written by hand. A
# name that carries ``.vN`` reaches only its live directory; the trash, a
# tombstone or a void does not hand it out again.
AT_2 = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def _live_runs(project) -> list[str]:
    return sorted(entry.name for entry in (project / RUNS_DIRNAME).iterdir())


def test_a_trashed_then_collected_version_is_not_reassigned(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    second = reserve_version_dirname(tmp_path, "run", "nancon")
    assert second.name == "nancon.v2"

    trash_run(tmp_path, "runs/nancon.v2", now=AT_2)
    freed = gc_trash(tmp_path, older_than=timedelta(0), now=AT_2 + timedelta(days=31))

    assert [tombstone.rel_dir for tombstone in freed] == ["runs/nancon.v2"]
    assert list_trash(tmp_path) == []
    assert _live_runs(tmp_path) == ["nancon"]
    assert [t.rel_dir for t in read_tombstones(tmp_path)] == ["runs/nancon.v2"]

    third = reserve_version_dirname(tmp_path, "run", "nancon")

    assert third.name == "nancon.v3"


def test_a_trashed_version_is_not_reassigned_before_the_gc(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    reserve_version_dirname(tmp_path, "run", "nancon")

    trash_run(tmp_path, "runs/nancon.v2", now=AT_2)
    assert _live_runs(tmp_path) == ["nancon"]

    third = reserve_version_dirname(tmp_path, "run", "nancon")

    assert third.name == "nancon.v3"


def test_the_bare_name_once_collected_is_not_reassigned(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    trash_run(tmp_path, "runs/nancon", now=AT_2)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT_2)

    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v2"


def _claim_2(project: Path, name: str, **kwargs: object) -> RunClaim:
    return claim_run_directory(project, name, case_id=name, project=project.name, **kwargs)


def _sealed_2(project: Path, name: str) -> Path:
    store = open_run_store(project, name, create_zarr=False)
    seal_completed(store)
    close_sealed_attempt(store.run_dir)
    return store.run_dir


def test_a_versioned_name_the_trash_holds_is_refused(tmp_path):
    _sealed_2(tmp_path, "a")
    assert _sealed_2(tmp_path, "a").name == "a.v2"
    trash_run(tmp_path, "runs/a.v2", now=AT_2)
    assert [entry.rel_dir for entry in list_trash(tmp_path)] == ["runs/a.v2"]

    with pytest.raises(NameTakenError, match=r"trash:runs/a\.v2.*name the case 'a'"):
        _claim_2(tmp_path, "a.v2")

    assert _live_runs(tmp_path) == ["a"]


def test_a_versioned_name_a_tombstone_holds_is_refused(tmp_path):
    _sealed_2(tmp_path, "nancon")
    _sealed_2(tmp_path, "nancon")
    trash_run(tmp_path, "runs/nancon", now=AT_2)
    trash_run(tmp_path, "runs/nancon.v2", now=AT_2)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT_2)
    assert "runs/nancon.v2" in [t.rel_dir for t in read_tombstones(tmp_path)]

    with pytest.raises(NameTakenError, match=r"tombstone:runs/nancon\.v2.*'nancon'"):
        _claim_2(tmp_path, "nancon.v2")

    assert _live_runs(tmp_path) == []


def test_a_versioned_name_nobody_holds_is_refused(tmp_path):
    (tmp_path / RUNS_DIRNAME).mkdir()

    with pytest.raises(NameTakenError, match="name the case 'fresh'"):
        _claim_2(tmp_path, "fresh.v2")

    assert _live_runs(tmp_path) == []


def test_a_versioned_name_retries_its_own_unfinished_directory(tmp_path):
    _sealed_2(tmp_path, "a")
    second = claim_run(tmp_path, "a")
    finish_attempt(second.run_dir, status="failed", exit_code=1)

    retry = _claim_2(tmp_path, "a.v2")

    assert retry.run_dir == second.run_dir
    assert retry.attempt == 2


def test_a_completed_versioned_name_takes_the_next_version_of_its_stem(tmp_path):
    _sealed_2(tmp_path, "a")
    _sealed_2(tmp_path, "a")
    _sealed_2(tmp_path, "a")
    trash_run(tmp_path, "runs/a.v3", now=AT_2)

    assert _claim_2(tmp_path, "a.v2").name == "a.v4"


def test_a_simulation_name_never_carries_its_version():
    with pytest.raises(ValidationError, match="write name = 'a'"):
        SimulationConfig(name="a.v2")

    assert SimulationConfig(name="a.vintage").name == "a.vintage"


# ``hmp catalog delete x --now`` once purged the live ``x.v2`` because a bare
# ``x`` meant "the latest version". Now ``x`` is ``runs/x`` exactly, a bare name
# with other versions is refused with the list, and a trashed directory is
# purged only by the trash verbs.
def _hmp(monkeypatch, *argv: str) -> int:
    main = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", ["hmp", *argv])
    try:
        main.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _project(tmp_path: Path, *names: str) -> Path:
    project = tmp_path / "p"
    project.mkdir()
    (project / "project.toml").write_text('[site]\nname = "p"\n', encoding="utf-8")
    for name in names:
        (project / "runs" / name).mkdir(parents=True)
    return project


def test_a_purge_of_a_trashed_name_touches_neither_the_trash_nor_the_live_run(
    tmp_path: Path, monkeypatch
) -> None:
    project = _project(tmp_path, "x", "x.v2")
    trash_run(project, "runs/x", now=AT)

    code = _hmp(monkeypatch, "catalog", "delete", "x", "--now", "-y", "-w", str(project))

    assert code == EXIT_NOT_FOUND
    assert (project / "runs" / "x.v2").is_dir()
    assert [entry.rel_dir for entry in list_trash(project)] == ["runs/x"]
    assert read_tombstones(project) == []


def test_a_purge_of_a_bare_name_with_versions_is_refused(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path, "x", "x.v2")

    code = _hmp(monkeypatch, "catalog", "delete", "x", "--now", "-y", "-w", str(project))

    assert code == EXIT_AMBIGUOUS_REFERENCE
    assert (project / "runs" / "x").is_dir()
    assert (project / "runs" / "x.v2").is_dir()


def test_a_purge_by_the_full_path_takes_exactly_that_directory(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path, "x", "x.v2")

    code = _hmp(monkeypatch, "catalog", "delete", "runs/x", "--now", "-y", "-w", str(project))

    assert code == 0
    assert not (project / "runs" / "x").exists()
    assert (project / "runs" / "x.v2").is_dir()
    assert [tombstone.rel_dir for tombstone in read_tombstones(project)] == ["runs/x"]


# The index keys ``simulations`` and ``tags`` on a UUID column. Compared as is,
# a free-text id made DuckDB raise a conversion error from the depths of the
# row lookup; compared as text, it is a run the index does not hold.
def test_a_free_text_id_reads_as_a_run_the_index_does_not_hold(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    sim_id = seal_run(project, "alpha")
    rebuild_index(project)
    catalog = Catalog(project)
    try:
        assert Run(sim_id, catalog).name == "alpha"
        with pytest.raises(RunNotFoundError):
            Run("not-a-uuid", catalog)._load_row()  # noqa: SLF001 - the row lookup itself
    finally:
        catalog.close()
