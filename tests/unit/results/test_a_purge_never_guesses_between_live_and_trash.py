"""A purge names one directory: never a guess between a live run and the trash.

``hmp catalog delete x --now`` once purged the live ``x.v2`` because a bare
``x`` meant "the latest version". Now ``x`` is ``runs/x`` exactly, a bare name
with other versions is refused with the list, and a trashed directory is
purged only by the trash verbs.
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_AMBIGUOUS_REFERENCE, EXIT_NOT_FOUND
from hydromodpy.results.trash import list_trash, read_tombstones, trash_run

AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


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
