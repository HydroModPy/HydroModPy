"""``hmp catalog tag`` and ``note`` write the run's ``annotations.json``, the truth."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from hydromodpy.results.annotations import read_annotations
from hydromodpy.results.manifest import RUN_RECORD_MANIFEST_VERSION

SIM_ID = "9a4f0c1e-0000-4000-8000-000000000001"


def _hmp(monkeypatch, *argv: str) -> int:
    main = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", ["hmp", *argv])
    try:
        main.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _run(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "p"
    run_dir = project / "runs" / "calibration"
    run_dir.mkdir(parents=True)
    (project / "project.toml").write_text('[site]\nname = "p"\n', encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps({"manifest_version": RUN_RECORD_MANIFEST_VERSION, "run": {"sim_id": SIM_ID}}),
        encoding="utf-8",
    )
    return project, run_dir


def test_tags_are_added_once_and_removed(tmp_path: Path, monkeypatch) -> None:
    project, run_dir = _run(tmp_path)
    w = ("-w", str(project))
    assert _hmp(monkeypatch, "catalog", "tag", "calibration", "pinned", "paper", *w) == 0
    assert _hmp(monkeypatch, "catalog", "tag", "calibration", "+paper", *w) == 0
    assert read_annotations(run_dir).tags == ("pinned", "paper")
    assert _hmp(monkeypatch, "catalog", "tag", "calibration", "--rm", "paper", *w) == 0
    assert read_annotations(run_dir).tags == ("pinned",)
    payload = json.loads((run_dir / "annotations.json").read_text(encoding="utf-8"))
    assert payload["sim_id"] == SIM_ID


def test_a_note_is_appended_with_its_instant(tmp_path: Path, monkeypatch) -> None:
    project, run_dir = _run(tmp_path)
    w = ("-w", str(project))
    assert _hmp(monkeypatch, "catalog", "note", "runs/calibration", "best fit", *w) == 0
    assert _hmp(monkeypatch, "catalog", "note", "calibration", "kept for the paper", *w) == 0
    notes = read_annotations(run_dir).notes
    assert [note.text for note in notes] == ["best fit", "kept for the paper"]
    assert all(note.at for note in notes)
    assert not (project / ".hmp").exists()


def test_an_indexed_run_keeps_its_row_and_note_after_a_note(tmp_path: Path, monkeypatch) -> None:
    import duckdb

    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog.indexer import rebuild_index
    from tests._helpers.sealed_runs import make_project, seal_run

    project = make_project(tmp_path / "p")
    seal_run(project, "first")
    rebuild_index(project)
    w = ("-w", str(project))
    assert _hmp(monkeypatch, "catalog", "note", "first", "a note", *w) == 0
    conn = duckdb.connect(str(catalog_path_for(project)), read_only=True)
    try:
        rel_dirs = [row[0] for row in conn.execute("SELECT rel_dir FROM simulations").fetchall()]
        notes = [row[0] for row in conn.execute("SELECT note FROM sim_notes").fetchall()]
    finally:
        conn.close()
    assert rel_dirs == ["runs/first"]
    assert notes == ["a note"]
