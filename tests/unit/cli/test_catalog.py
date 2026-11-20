"""``hmp catalog``: query the index, tag and note a run, trash and restore it, import a published one.

The index ``.hmp/index.duckdb`` is derived from the sealed runs under ``runs/``. Reading never changes
it. Tags and notes live in ``annotations.json`` beside the run and follow it into the index.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from hydromodpy.cli.exit_codes import EXIT_NOT_FOUND, EXIT_WRITE_CONFLICT
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.results.annotations import read_annotations
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.publication import Publication, PublicationSource, write_publication
from tests._helpers.sealed_runs import make_project, manifest_document, seal_run

from ._hmp import run_hmp as hmp

SIM_ID = "9a4f0c1e-0000-4000-8000-000000000001"

# Commands that read the index and must leave it byte for byte.
READS = [
    pytest.param(["ls"], id="ls"),
    pytest.param(["show", "alpha"], id="show"),
    pytest.param(["catalog", "query", "SELECT COUNT(*) FROM simulations"], id="query"),
]


@pytest.fixture
def indexed_project(tmp_path) -> Path:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha", mesh_engine=None)
    seal_run(root, "voronoi_run", mesh_engine="voronoi", config_text='[mesh]\nengine = "voronoi"\n')
    rebuild_index(root)
    return root


def calibration_run(tmp_path: Path) -> tuple[Path, Path]:
    """A project with one run folder that holds a manifest and nothing else."""
    project = tmp_path / "p"
    run_dir = project / "runs" / "calibration"
    run_dir.mkdir(parents=True)
    (project / "project.toml").write_text('[site]\nname = "p"\n', encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest_document(sim_id=SIM_ID)), encoding="utf-8"
    )
    return project, run_dir


def published_copy(tmp_path: Path) -> Path:
    copy = tmp_path / "copy"
    (copy / "tables.parquet").mkdir(parents=True)
    (copy / "tables.parquet" / "simulation.parquet").write_bytes(b"PAR1")
    (copy / "manifest.json").write_text(
        json.dumps(manifest_document(sim_id=SIM_ID)), encoding="utf-8"
    )
    files = {
        path.relative_to(copy).as_posix(): sha256_of(path)
        for path in sorted(copy.rglob("*"))
        if path.is_file()
    }
    publication = Publication(
        source=PublicationSource(project="lab", rel_dir="runs/nancon_monthly", sim_id=SIM_ID),
        files=files,
        hydromodpy_version="2.0.0a5",
        published_at=datetime(2026, 10, 15, tzinfo=UTC),
        format="dir",
    )
    write_publication(copy, publication)
    return copy


def project_to_import_into(tmp_path: Path) -> Path:
    project = tmp_path / "home"
    project.mkdir()
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    return project


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_query_of_a_workspace_without_catalog_is_not_found(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "empty_ws"
    missing.mkdir()

    assert hmp(monkeypatch, "catalog", "query", "SELECT 1", "--workspace", str(missing)) == 10


def test_query_runs_on_an_existing_catalog(monkeypatch, indexed_project, capsys) -> None:
    code = hmp(
        monkeypatch, "catalog", "query", "SELECT 1 AS one", "--workspace", str(indexed_project)
    )

    assert code == 0
    assert "one" in capsys.readouterr().out


@pytest.mark.parametrize("argv", READS)
def test_reading_leaves_the_index_byte_for_byte(monkeypatch, indexed_project, argv) -> None:
    index = catalog_path_for(indexed_project)
    before = digest(index)
    mtime = index.stat().st_mtime_ns

    assert hmp(monkeypatch, *argv, "--workspace", str(indexed_project)) == 0

    assert digest(index) == before
    assert index.stat().st_mtime_ns == mtime


def test_a_reader_refuses_to_write(indexed_project) -> None:
    with Catalog(indexed_project) as catalog:
        with pytest.raises(Exception, match="read-only|Cannot execute|read_only"):
            catalog.backend.execute("DELETE FROM simulations")


def test_tags_are_added_once_and_removed(tmp_path: Path, monkeypatch) -> None:
    project, run_dir = calibration_run(tmp_path)
    w = ("-w", str(project))

    assert hmp(monkeypatch, "catalog", "tag", "calibration", "pinned", "paper", *w) == 0
    assert hmp(monkeypatch, "catalog", "tag", "calibration", "+paper", *w) == 0
    assert read_annotations(run_dir).tags == ("pinned", "paper")
    assert hmp(monkeypatch, "catalog", "tag", "calibration", "--rm", "paper", *w) == 0
    assert read_annotations(run_dir).tags == ("pinned",)
    payload = json.loads((run_dir / "annotations.json").read_text(encoding="utf-8"))
    assert payload["sim_id"] == SIM_ID


def test_a_note_is_appended_with_its_instant(tmp_path: Path, monkeypatch) -> None:
    project, run_dir = calibration_run(tmp_path)
    w = ("-w", str(project))

    assert hmp(monkeypatch, "catalog", "note", "runs/calibration", "best fit", *w) == 0
    assert hmp(monkeypatch, "catalog", "note", "calibration", "kept for the paper", *w) == 0

    notes = read_annotations(run_dir).notes
    assert [note.text for note in notes] == ["best fit", "kept for the paper"]
    assert all(note.at for note in notes)
    assert not (project / ".hmp").exists()


def test_an_indexed_run_keeps_its_row_and_note_after_a_note(tmp_path: Path, monkeypatch) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "first")
    rebuild_index(project)

    assert hmp(monkeypatch, "catalog", "note", "first", "a note", "-w", str(project)) == 0

    conn = duckdb.connect(str(catalog_path_for(project)), read_only=True)
    try:
        rel_dirs = [row[0] for row in conn.execute("SELECT rel_dir FROM simulations").fetchall()]
        notes = [row[0] for row in conn.execute("SELECT note FROM sim_notes").fetchall()]
    finally:
        conn.close()
    assert rel_dirs == ["runs/first"]
    assert notes == ["a note"]


def test_trash_moves_the_run_and_restore_brings_it_back(
    monkeypatch, capsys, indexed_project
) -> None:
    w = ("-w", str(indexed_project))

    assert hmp(monkeypatch, "catalog", "trash", "alpha", *w) == 0
    assert "moved runs/alpha to" in capsys.readouterr().out
    assert not (indexed_project / "runs" / "alpha").exists()

    assert hmp(monkeypatch, "catalog", "trash", *w) == 0
    trashed = capsys.readouterr().out
    assert "runs/alpha" in trashed or "runs__alpha" in trashed

    assert hmp(monkeypatch, "catalog", "restore", "alpha", *w) == 0
    assert "restored runs/alpha" in capsys.readouterr().out
    assert (indexed_project / "runs" / "alpha").is_dir()


def test_trash_dry_run_moves_nothing(monkeypatch, capsys, indexed_project) -> None:
    code = hmp(monkeypatch, "catalog", "trash", "alpha", "--dry-run", "-w", str(indexed_project))

    assert code == 0
    assert "would move runs/alpha to trash/" in capsys.readouterr().out
    assert (indexed_project / "runs" / "alpha").is_dir()


def test_trash_moves_the_run_it_announces_when_a_session_shares_the_name(
    monkeypatch, capsys, indexed_project
) -> None:
    session = indexed_project / "sessions" / "alpha"
    session.mkdir(parents=True)
    (session / "session.json").write_text("{}", encoding="utf-8")
    w = ("-w", str(indexed_project))

    assert hmp(monkeypatch, "catalog", "trash", "alpha", "--dry-run", *w) == 0
    assert "would move runs/alpha to trash/" in capsys.readouterr().out
    assert hmp(monkeypatch, "catalog", "trash", "alpha", *w) == 0
    assert "moved runs/alpha to" in capsys.readouterr().out
    assert not (indexed_project / "runs" / "alpha").exists()
    assert session.is_dir()


def test_trash_refuses_a_reference_beside_empty(monkeypatch, indexed_project) -> None:
    code = hmp(monkeypatch, "catalog", "trash", "alpha", "--empty", "-w", str(indexed_project))

    assert code == 2


def test_reindex_appears_in_the_catalog_help(monkeypatch, capsys) -> None:
    assert hmp(monkeypatch, "catalog", "--help") == 0
    assert "reindex" in capsys.readouterr().out


def test_a_published_tar_is_imported_under_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    archive = tmp_path / "nancon_monthly.tar"
    with tarfile.open(archive, "w") as handle:
        handle.add(published_copy(tmp_path), arcname="nancon_monthly")
    project = project_to_import_into(tmp_path)

    assert hmp(monkeypatch, "catalog", "import", str(archive), "-w", str(project)) == 0

    assert (project / "runs" / "nancon_monthly" / "manifest.json").is_file()
    assert "runs/nancon_monthly" in capsys.readouterr().out


def test_a_second_import_of_the_same_run_is_a_write_conflict(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    copy = published_copy(tmp_path)
    project = project_to_import_into(tmp_path)
    assert hmp(monkeypatch, "catalog", "import", str(copy), "-w", str(project)) == 0
    shutil.copytree(copy, tmp_path / "again")

    code = hmp(monkeypatch, "catalog", "import", str(tmp_path / "again"), "-w", str(project))

    assert code == EXIT_WRITE_CONFLICT
    assert "already in this project" in capsys.readouterr().err


def test_an_import_of_a_missing_source_is_not_found(tmp_path: Path, monkeypatch) -> None:
    project = project_to_import_into(tmp_path)

    code = hmp(monkeypatch, "catalog", "import", str(tmp_path / "nope.tar"), "-w", str(project))

    assert code == EXIT_NOT_FOUND
