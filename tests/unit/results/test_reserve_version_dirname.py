"""``reserve_version_dirname``: the version is read on disk, ``mkdir`` makes the claim atomic."""

from __future__ import annotations

import multiprocessing
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import (
    RUNS_DIRNAME,
    SESSIONS_DIRNAME,
    TOMBSTONES_FILENAME,
    TRASH_DIRNAME,
)
from hydromodpy.results.catalog import registration
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.trash import trashed_dirname

AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def _names(tree: Path) -> list[str]:
    return sorted(entry.name for entry in tree.iterdir())


def test_the_bare_name_is_version_one(tmp_path):
    reserved = reserve_version_dirname(tmp_path, "run", "nancon")

    assert reserved == tmp_path / RUNS_DIRNAME / "nancon"
    assert reserved.is_dir()


def test_the_next_run_of_a_live_name_is_the_next_version(tmp_path):
    reserve_version_dirname(tmp_path, "run", "nancon")
    reserve_version_dirname(tmp_path, "run", "nancon")

    third = reserve_version_dirname(tmp_path, "run", "nancon")

    assert third.name == "nancon.v3"
    assert _names(tmp_path / RUNS_DIRNAME) == ["nancon", "nancon.v2", "nancon.v3"]


def test_a_session_is_created_under_sessions(tmp_path):
    reserved = reserve_version_dirname(tmp_path, "session", "calibration")

    assert reserved == tmp_path / SESSIONS_DIRNAME / "calibration"


def test_runs_and_sessions_share_one_version_space(tmp_path):
    reserve_version_dirname(tmp_path, "session", "calibration")

    unpaired = reserve_version_dirname(tmp_path, "run", "calibration")

    assert unpaired.name == "calibration.v2"


def test_a_promoted_run_takes_the_version_of_its_session(tmp_path):
    first = reserve_version_dirname(tmp_path, "session", "calibration")
    second = reserve_version_dirname(tmp_path, "session", "calibration")

    run_first = reserve_version_dirname(tmp_path, "run", "calibration", pair_with=first)
    run_second = reserve_version_dirname(tmp_path, "run", "calibration", pair_with=second)

    assert (first.name, second.name) == ("calibration", "calibration.v2")
    assert run_first == tmp_path / RUNS_DIRNAME / "calibration"
    assert run_second == tmp_path / RUNS_DIRNAME / "calibration.v2"
    assert run_first.is_dir() and run_second.is_dir()


def test_pairing_fails_when_the_run_directory_is_taken(tmp_path):
    session = reserve_version_dirname(tmp_path, "session", "calibration")
    (tmp_path / RUNS_DIRNAME / "calibration").mkdir(parents=True)

    with pytest.raises(registration.VersionPairingError, match="calibration"):
        reserve_version_dirname(tmp_path, "run", "calibration", pair_with=session)


def test_pairing_refuses_a_directory_of_another_name(tmp_path):
    session = reserve_version_dirname(tmp_path, "session", "calibration")

    with pytest.raises(ValueError, match="not a version of"):
        reserve_version_dirname(tmp_path, "run", "nancon", pair_with=session)


def test_the_highest_version_counts_not_the_number_of_directories(tmp_path):
    (tmp_path / RUNS_DIRNAME / "nancon.v7").mkdir(parents=True)

    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v8"


def test_another_stem_does_not_count(tmp_path):
    for name in ("nancon_daily", "nancon_daily.v4", "nancon2"):
        (tmp_path / RUNS_DIRNAME / name).mkdir(parents=True, exist_ok=True)

    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon"


def test_a_trashed_version_counts_by_its_original_name(tmp_path):
    trash = tmp_path / TRASH_DIRNAME
    trash.mkdir()
    (trash / trashed_dirname("runs/nancon.v3", AT)).mkdir()

    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v4"


def test_a_tombstoned_version_counts(tmp_path):
    trash = tmp_path / TRASH_DIRNAME
    trash.mkdir()
    (trash / TOMBSTONES_FILENAME).write_text(
        "sessions/nancon.v5,,2026-10-14T09:30:00Z\n", encoding="utf-8"
    )

    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v6"


def test_a_name_with_a_version_suffix_is_refused(tmp_path):
    with pytest.raises(ValueError, match="bare name 'nancon'"):
        reserve_version_dirname(tmp_path, "run", "nancon.v2")


def test_a_name_that_is_not_a_directory_name_is_refused(tmp_path):
    with pytest.raises(ValueError, match="nancon_amont"):
        reserve_version_dirname(tmp_path, "run", "nancon amont")


def test_a_lost_mkdir_race_computes_the_version_again(tmp_path, monkeypatch):
    """A neighbour creates the directory between the computation and the mkdir."""
    real_mkdir = os.mkdir
    stolen: list[str] = []

    def neighbour_wins_once(path, *args, **kwargs):
        if not stolen and Path(path).parent.name == RUNS_DIRNAME:
            stolen.append(Path(path).name)
            real_mkdir(path)
            raise FileExistsError(path)
        return real_mkdir(path, *args, **kwargs)

    reserve_version_dirname(tmp_path, "run", "nancon")
    monkeypatch.setattr(registration.os, "mkdir", neighbour_wins_once)

    mine = reserve_version_dirname(tmp_path, "run", "nancon")

    assert stolen == ["nancon.v2"]
    assert mine.name == "nancon.v3"


_RESERVATIONS_PER_PROCESS = 12


def _reserve_many(project_root: str, barrier, queue) -> None:
    """Child process: wait for the sibling, then reserve the same run name repeatedly."""
    barrier.wait()
    names = [
        reserve_version_dirname(Path(project_root), "run", "case").name
        for _ in range(_RESERVATIONS_PER_PROCESS)
    ]
    queue.put(names)


def test_two_processes_reserving_one_name_never_get_the_same_version(tmp_path):
    reserve_version_dirname(tmp_path, "run", "case")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(target=_reserve_many, args=(str(tmp_path), barrier, queue))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=120) for _ in workers]
    for worker in workers:
        worker.join(timeout=120)
        assert worker.exitcode == 0

    reserved = [name for names in results for name in names]
    expected = {f"case.v{n}" for n in range(2, 2 + 2 * _RESERVATIONS_PER_PROCESS)}
    assert len(reserved) == len(set(reserved)), "a version was given out twice"
    assert set(reserved) == expected
    assert _names(tmp_path / RUNS_DIRNAME) == sorted({"case", *expected})
