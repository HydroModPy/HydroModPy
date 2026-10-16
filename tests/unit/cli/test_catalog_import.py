"""``hmp catalog import`` brings a run written by ``hmp publish`` under ``runs/``."""

from __future__ import annotations

import importlib
import json
import shutil
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_WRITE_CONFLICT
from hydromodpy.results.ledger import sha256_of
from hydromodpy.results.manifest import RUN_RECORD_MANIFEST_VERSION
from hydromodpy.results.publication import Publication, PublicationSource, write_publication

SIM_ID = "9a4f0c1e-0000-4000-8000-000000000001"


def _hmp(monkeypatch, *argv: str) -> int:
    main = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", ["hmp", *argv])
    try:
        main.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _published(tmp_path: Path) -> Path:
    copy = tmp_path / "copy"
    (copy / "tables.parquet").mkdir(parents=True)
    (copy / "tables.parquet" / "simulation.parquet").write_bytes(b"PAR1")
    (copy / "manifest.json").write_text(
        json.dumps({"manifest_version": RUN_RECORD_MANIFEST_VERSION, "run": {"sim_id": SIM_ID}}),
        encoding="utf-8",
    )
    files = {
        path.relative_to(copy).as_posix(): sha256_of(path)
        for path in sorted(copy.rglob("*"))
        if path.is_file()
    }
    write_publication(
        copy,
        Publication(
            source=PublicationSource(project="lab", rel_dir="runs/nancon_monthly", sim_id=SIM_ID),
            files=files,
            hydromodpy_version="2.0.0a5",
            published_at=datetime(2026, 10, 15, tzinfo=UTC),
            format="dir",
        ),
    )
    return copy


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "home"
    project.mkdir()
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    return project


def test_a_published_tar_is_imported_under_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    copy = _published(tmp_path)
    archive = tmp_path / "nancon_monthly.tar"
    with tarfile.open(archive, "w") as handle:
        handle.add(copy, arcname="nancon_monthly")
    project = _project(tmp_path)

    assert _hmp(monkeypatch, "catalog", "import", str(archive), "-w", str(project)) == 0

    assert (project / "runs" / "nancon_monthly" / "manifest.json").is_file()
    assert "runs/nancon_monthly" in capsys.readouterr().out


def test_a_second_import_of_the_same_run_is_a_write_conflict(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    copy = _published(tmp_path)
    project = _project(tmp_path)
    assert _hmp(monkeypatch, "catalog", "import", str(copy), "-w", str(project)) == 0
    shutil.copytree(copy, tmp_path / "again")

    code = _hmp(monkeypatch, "catalog", "import", str(tmp_path / "again"), "-w", str(project))

    assert code == EXIT_WRITE_CONFLICT
    assert "already in this project" in capsys.readouterr().err


def test_a_missing_source_is_not_found(tmp_path: Path, monkeypatch) -> None:
    from hydromodpy.cli.helpers import EXIT_NOT_FOUND

    project = _project(tmp_path)
    code = _hmp(monkeypatch, "catalog", "import", str(tmp_path / "nope.tar"), "-w", str(project))
    assert code == EXIT_NOT_FOUND
