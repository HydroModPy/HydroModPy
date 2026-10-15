"""The trash moves directories: out of ``runs/`` on trash, back on restore, gone on gc."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    RUNS_DIRNAME,
    SESSIONS_DIRNAME,
    TOMBSTONES_FILENAME,
    TRASH_DIRNAME,
)
from hydromodpy.results.session.descriptor import SessionDescriptor, write_session
from hydromodpy.results.storage.contract import (
    RUN_MANIFEST_FILENAME,
    RUN_PUBLISHED_FILENAME,
)
from hydromodpy.results.trash import (
    Tombstone,
    gc_trash,
    list_trash,
    parse_trashed_dirname,
    read_tombstones,
    restore,
    trash_run,
    trashed_dirname,
)

AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
SIM_ID = "9a4f0c1e-0000-4000-8000-000000000001"


def _make_run(project: Path, name: str, *, sim_id: str | None = None) -> Path:
    run_dir = project / RUNS_DIRNAME / name
    (run_dir / "tables.parquet").mkdir(parents=True)
    (run_dir / "tables.parquet" / "simulation.parquet").write_bytes(b"PAR1-demo-bytes")
    (run_dir / "config.toml").write_text("[flow]\nk = 1e-5\n", encoding="utf-8")
    if sim_id is not None:
        manifest = {"run": {"sim_id": sim_id, "name": name}}
        (run_dir / RUN_MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def _tree(directory: Path) -> dict[str, str]:
    """Relative path -> sha256 of every file below ``directory``."""
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def warnings_said(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Let ``caplog`` see the ``hydromodpy`` warnings, which stop propagating by default."""
    parent = get_logger("hydromodpy")
    propagate = parent.propagate
    parent.propagate = True
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    try:
        yield caplog
    finally:
        parent.propagate = propagate


def test_trashing_a_run_moves_its_directory(tmp_path):
    run_dir = _make_run(tmp_path, "nancon_daily")
    before = _tree(run_dir)

    trashed = trash_run(tmp_path, "runs/nancon_daily", now=AT)

    assert not run_dir.exists()
    assert trashed == tmp_path / TRASH_DIRNAME / "runs__nancon_daily@20261014T093000"
    assert _tree(trashed) == before


def test_a_restored_run_is_identical(tmp_path):
    run_dir = _make_run(tmp_path, "nancon_daily", sim_id=SIM_ID)
    before = _tree(run_dir)
    trashed = trash_run(tmp_path, "runs/nancon_daily", now=AT)

    restored = restore(tmp_path, trashed.name)

    assert restored == run_dir
    assert _tree(run_dir) == before
    assert list_trash(tmp_path) == []


def test_a_session_is_trashed_and_restored_too(tmp_path):
    session = tmp_path / SESSIONS_DIRNAME / "calibration"
    (session / "phases").mkdir(parents=True)
    (session / "trials.jsonl").write_text('{"trial": 1}\n', encoding="utf-8")
    before = _tree(session)

    trashed = trash_run(tmp_path, "sessions/calibration", now=AT)

    assert trashed.name == "sessions__calibration@20261014T093000"
    assert not session.exists()
    [entry] = list_trash(tmp_path)
    assert entry.rel_dir == "sessions/calibration"
    restore(tmp_path, trashed.name)
    assert _tree(session) == before


def test_the_trashed_name_decodes_to_the_relative_directory(tmp_path):
    name = trashed_dirname("sessions/calibration/trials/0004", AT)

    assert name == "sessions__calibration__trials__0004@20261014T093000"
    assert parse_trashed_dirname(name) == ("sessions/calibration/trials/0004", AT)


def test_a_name_the_trash_did_not_write_is_refused():
    with pytest.raises(ValueError):
        parse_trashed_dirname("nancon_daily")


def test_trashing_a_missing_directory_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="runs/ghost"):
        trash_run(tmp_path, "runs/ghost", now=AT)


def test_a_restore_onto_an_existing_directory_is_refused(tmp_path):
    _make_run(tmp_path, "nancon_daily")
    trashed = trash_run(tmp_path, "runs/nancon_daily", now=AT)
    (tmp_path / RUNS_DIRNAME / "nancon_daily").mkdir()

    with pytest.raises(FileExistsError, match="runs/nancon_daily"):
        restore(tmp_path, trashed.name)
    assert trashed.is_dir()


def test_trashing_a_published_run_warns(tmp_path, warnings_said):
    run_dir = _make_run(tmp_path, "nancon_daily")
    (run_dir / RUN_PUBLISHED_FILENAME).write_text('{"to": "/srv/out"}\n', encoding="utf-8")

    trash_run(tmp_path, "runs/nancon_daily", now=AT)

    assert any(
        "published" in record.getMessage() and record.levelno == logging.WARNING
        for record in warnings_said.records
    )


def test_trashing_an_unpublished_run_is_silent(tmp_path, warnings_said):
    _make_run(tmp_path, "nancon_daily")

    trash_run(tmp_path, "runs/nancon_daily", now=AT)

    assert warnings_said.records == []


def test_the_trash_lists_oldest_first_and_skips_foreign_entries(tmp_path):
    _make_run(tmp_path, "a")
    _make_run(tmp_path, "b")
    trash_run(tmp_path, "runs/b", now=AT)
    trash_run(tmp_path, "runs/a", now=AT + timedelta(hours=1))
    (tmp_path / TRASH_DIRNAME / "made_by_hand").mkdir()

    assert [entry.rel_dir for entry in list_trash(tmp_path)] == ["runs/b", "runs/a"]


def test_gc_writes_the_tombstones_and_empties_the_trash(tmp_path):
    _make_run(tmp_path, "nancon_daily", sim_id=SIM_ID)
    trashed = trash_run(tmp_path, "runs/nancon_daily", now=AT)
    gc_at = AT + timedelta(days=31)

    freed = gc_trash(tmp_path, older_than=timedelta(days=30), now=gc_at)

    assert freed == [Tombstone(rel_dir="runs/nancon_daily", sim_id=SIM_ID, date=gc_at)]
    assert not trashed.exists()
    assert list_trash(tmp_path) == []
    text = (tmp_path / TRASH_DIRNAME / TOMBSTONES_FILENAME).read_text(encoding="utf-8")
    assert text == f"runs/nancon_daily,{SIM_ID},2026-11-14T09:30:00Z\n"
    assert read_tombstones(tmp_path) == freed


def test_gc_keeps_what_is_younger_than_the_threshold(tmp_path):
    _make_run(tmp_path, "old")
    _make_run(tmp_path, "recent")
    trash_run(tmp_path, "runs/old", now=AT)
    trash_run(tmp_path, "runs/recent", now=AT + timedelta(days=20))

    freed = gc_trash(tmp_path, older_than=timedelta(days=30), now=AT + timedelta(days=31))

    assert [tombstone.rel_dir for tombstone in freed] == ["runs/old"]
    assert [entry.rel_dir for entry in list_trash(tmp_path)] == ["runs/recent"]


def test_a_second_gc_appends_to_the_tombstones(tmp_path):
    _make_run(tmp_path, "a")
    _make_run(tmp_path, "b")
    trash_run(tmp_path, "runs/a", now=AT)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT)
    trash_run(tmp_path, "runs/b", now=AT)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT)

    assert [t.rel_dir for t in read_tombstones(tmp_path)] == ["runs/a", "runs/b"]


def test_a_collected_session_tombstone_carries_its_session_id(tmp_path):
    session = tmp_path / SESSIONS_DIRNAME / "calibration"
    session.mkdir(parents=True)
    write_session(
        session,
        SessionDescriptor(
            session_id="5b0c9d2e",
            case_id="calibration",
            config_hash="abc123",
            hydromodpy_version="2.0.0a5",
            method="cmaes",
            objective_name="nse",
            started_at=AT,
        ),
    )
    trash_run(tmp_path, "sessions/calibration", now=AT)

    [tombstone] = gc_trash(tmp_path, older_than=timedelta(0), now=AT)

    assert tombstone.rel_dir == "sessions/calibration"
    assert tombstone.sim_id == "5b0c9d2e"


def test_a_malformed_tombstone_names_its_line(tmp_path):
    trash = tmp_path / TRASH_DIRNAME
    trash.mkdir()
    (trash / TOMBSTONES_FILENAME).write_text(
        "runs/a,,2026-10-14T09:30:00Z\nruns/b;oops\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match=f"{TOMBSTONES_FILENAME}:2"):
        read_tombstones(tmp_path)
