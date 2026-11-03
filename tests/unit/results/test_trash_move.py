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
from hydromodpy.results.session.descriptor import write_session
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
from tests._helpers.sealed_runs import manifest_document
from tests._helpers.session_documents import session_descriptor

AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
SIM_ID = "9a4f0c1e-0000-4000-8000-000000000001"


def _make_run(project: Path, name: str, *, sim_id: str | None = None) -> Path:
    run_dir = project / RUNS_DIRNAME / name
    (run_dir / "tables.parquet").mkdir(parents=True)
    (run_dir / "tables.parquet" / "simulation.parquet").write_bytes(b"PAR1-demo-bytes")
    (run_dir / "config.toml").write_text("[flow]\nk = 1e-5\n", encoding="utf-8")
    if sim_id is not None:
        (run_dir / RUN_MANIFEST_FILENAME).write_text(
            json.dumps(manifest_document(sim_id=sim_id, name=name)), encoding="utf-8"
        )
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
        session_descriptor("calibration", session_id="5b0c9d2e", method="cmaes", started_at=AT),
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


# ---------------------------------------------------------------------------
# The CLI verbs on top of the trash: delete, restore, trash, and what they guard.
# ---------------------------------------------------------------------------


def _hmp(monkeypatch, *argv: str) -> int:
    import importlib
    import sys

    main = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", ["hmp", *argv])
    try:
        main.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "nancon"
    project.mkdir()
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    return project


def _write_outcome(run_dir: Path, status: str, *, started_at: datetime) -> None:
    import os

    from hydromodpy.results.outcome import Outcome, write_outcome

    write_outcome(
        run_dir,
        Outcome(
            case_id=run_dir.name,
            attempt=1,
            attempt_id="a1",
            sim_id=SIM_ID,
            status=status,
            written_by="worker",
            started_at=started_at,
            ended_at=None if status == "running" else started_at,
            host="here",
            pid=os.getpid(),
        ),
    )


def test_delete_moves_the_named_directory_and_restore_brings_it_back(tmp_path, monkeypatch):
    project = _project(tmp_path)
    run_dir = _make_run(project, "nancon_daily", sim_id=SIM_ID)
    before = _tree(run_dir)

    assert _hmp(monkeypatch, "catalog", "delete", "nancon_daily", "-y", "-w", str(project)) == 0
    assert not run_dir.exists()
    [entry] = list_trash(project)
    assert entry.rel_dir == "runs/nancon_daily"

    assert _hmp(monkeypatch, "catalog", "restore", "nancon_daily", "-w", str(project)) == 0
    assert _tree(run_dir) == before
    assert not (project / ".hmp" / "index.duckdb").exists()


def test_delete_of_a_bare_name_with_versions_is_refused_with_the_list(
    tmp_path, monkeypatch, capsys
):
    from hydromodpy.cli.helpers import EXIT_AMBIGUOUS_REFERENCE

    project = _project(tmp_path)
    _make_run(project, "J0014010-base")
    _make_run(project, "J0014010-base.v2")

    code = _hmp(monkeypatch, "catalog", "delete", "J0014010-base", "-y", "-w", str(project))

    assert code == EXIT_AMBIGUOUS_REFERENCE
    err = capsys.readouterr().err
    assert "runs/J0014010-base.v2" in err
    assert (project / RUNS_DIRNAME / "J0014010-base").is_dir()
    assert _hmp(monkeypatch, "catalog", "delete", "J0014010-base.v2", "-y", "-w", str(project)) == 0
    assert not (project / RUNS_DIRNAME / "J0014010-base.v2").exists()


def test_delete_now_leaves_a_tombstone_and_the_name_stays_taken(tmp_path, monkeypatch):
    from hydromodpy.results.catalog.registration import reserve_version_dirname

    project = _project(tmp_path)
    _make_run(project, "x", sim_id=SIM_ID)
    _make_run(project, "x.v2")

    assert _hmp(monkeypatch, "catalog", "delete", "x.v2", "--now", "-y", "-w", str(project)) == 0

    assert list_trash(project) == []
    [tombstone] = read_tombstones(project)
    assert tombstone.rel_dir == "runs/x.v2"
    assert reserve_version_dirname(project, "run", "x").name == "x.v3"


def test_delete_refuses_a_pinned_run_without_force(tmp_path, monkeypatch, capsys):
    from hydromodpy.cli.helpers import EXIT_WRITE_CONFLICT

    project = _project(tmp_path)
    _make_run(project, "best", sim_id=SIM_ID)
    assert _hmp(monkeypatch, "catalog", "tag", "best", "pinned", "-w", str(project)) == 0

    code = _hmp(monkeypatch, "catalog", "delete", "best", "-y", "-w", str(project))
    assert code == EXIT_WRITE_CONFLICT
    assert "pinned" in capsys.readouterr().err
    assert _hmp(monkeypatch, "catalog", "delete", "best", "-y", "--force", "-w", str(project)) == 0


def test_delete_never_moves_a_running_attempt(tmp_path, monkeypatch, capsys):
    from hydromodpy.cli.helpers import EXIT_WRITE_CONFLICT

    project = _project(tmp_path)
    run_dir = _make_run(project, "busy")
    _write_outcome(run_dir, "running", started_at=datetime.now(UTC))

    code = _hmp(monkeypatch, "catalog", "delete", "busy", "-y", "--force", "-w", str(project))
    assert code == EXIT_WRITE_CONFLICT
    assert "running" in capsys.readouterr().err
    assert run_dir.is_dir()


def test_trash_lists_and_empty_leaves_tombstones_and_spares_pinned(tmp_path, monkeypatch, capsys):
    import json as _json

    project = _project(tmp_path)
    _make_run(project, "a", sim_id=SIM_ID)
    _make_run(project, "b")
    assert _hmp(monkeypatch, "catalog", "tag", "b", "pinned", "-w", str(project)) == 0
    trash_run(project, "runs/a", now=AT)
    trash_run(project, "runs/b", now=AT, force=True)
    capsys.readouterr()

    assert _hmp(monkeypatch, "catalog", "trash", "--format", "json", "-w", str(project)) == 0
    listed = _json.loads(capsys.readouterr().out)["data"]
    assert [row["rel_dir"] for row in listed] == ["runs/a", "runs/b"]

    assert _hmp(monkeypatch, "catalog", "trash", "--empty", "-y", "-w", str(project)) == 0
    assert [entry.rel_dir for entry in list_trash(project)] == ["runs/b"]
    assert [tombstone.rel_dir for tombstone in read_tombstones(project)] == ["runs/a"]


def test_trashing_a_published_run_through_the_cli_warns(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    run_dir = _make_run(project, "handed_out")
    (run_dir / RUN_PUBLISHED_FILENAME).write_text("{}\n", encoding="utf-8")

    assert _hmp(monkeypatch, "catalog", "delete", "handed_out", "-y", "-w", str(project)) == 0

    assert "published copies now point at a trashed source" in capsys.readouterr().err


def test_a_verb_that_moves_a_directory_refreshes_an_index_that_exists(tmp_path, monkeypatch):
    import hydromodpy.results.catalog.indexer as indexer

    project = _project(tmp_path)
    _make_run(project, "a")
    indexer.index_new_runs(project)
    calls: list[Path] = []
    monkeypatch.setattr(indexer, "index_new_runs", lambda root, **_: calls.append(Path(root)))

    assert _hmp(monkeypatch, "catalog", "delete", "a", "-y", "-w", str(project)) == 0
    assert _hmp(monkeypatch, "catalog", "restore", "a", "-w", str(project)) == 0

    assert calls == [project, project]
