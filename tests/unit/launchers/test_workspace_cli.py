"""Unit tests for ``hmp workspace`` CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG
from hydromodpy.cli.main import main
from hydromodpy.core.state.layout import (
    INTERNAL_DIRNAME,
    catalog_path_for,
    runs_dir_for,
    trash_dir_for,
)
from hydromodpy.core.state.scratch import scratch_dir_for
from hydromodpy.data.provenance.sidecars import FORMER_CACHE_DATABASE
from hydromodpy.results.trash import parse_trashed_dirname
from tests._helpers.sealed_runs import seal_run


def _seed_workspace(root: Path) -> None:
    (root / "data" / "source").mkdir(parents=True)
    (root / "data" / "source" / "keep.csv").write_text("value\n1\n", encoding="utf-8")
    (root / "data" / "blobs").mkdir(parents=True)
    (root / "data" / "blobs" / "generated.bin").write_bytes(b"blob")
    for suffix in ("", ".wal", ".lock"):
        (root / "data" / f"{FORMER_CACHE_DATABASE}{suffix}").write_bytes(b"duckdb")
    sidecar_file = root / "data" / "dem" / "dem_ign_a.tif"
    sidecar_file.parent.mkdir(parents=True)
    sidecar_file.write_bytes(b"tif")
    sidecar_file.with_name(sidecar_file.name + ".json").write_text("{}", encoding="utf-8")
    (root / INTERNAL_DIRNAME).mkdir()
    project = root / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "project.toml").write_text("", encoding="utf-8")
    catalog_path_for(project).parent.mkdir(parents=True, exist_ok=True)
    catalog_path_for(project).write_bytes(b"duckdb")
    seal_run(project, "demo_run")
    scratch_dir_for(project).mkdir(parents=True, exist_ok=True)


def test_workspace_clean_dry_run_keeps_files(monkeypatch, tmp_path: Path, capsys) -> None:
    _seed_workspace(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["hmp", "workspace", "clean", "--workspace", str(tmp_path), "--all"],
    )

    main()

    out = capsys.readouterr().out
    assert "Dry-run" in out
    project = tmp_path / "projects" / "demo"
    assert catalog_path_for(project).exists()
    assert runs_dir_for(project).exists()
    assert (tmp_path / "data" / FORMER_CACHE_DATABASE).exists()


def test_workspace_clean_all_trashes_the_runs_and_deletes_the_caches(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _seed_workspace(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["hmp", "workspace", "clean", "--workspace", str(tmp_path), "--all", "--yes"],
    )

    main()

    project = tmp_path / "projects" / "demo"
    assert not catalog_path_for(project).exists()
    assert not (runs_dir_for(project) / "demo_run").exists()
    trashed = [parse_trashed_dirname(path.name)[0] for path in trash_dir_for(project).iterdir()]
    assert "runs/demo_run" in trashed
    for suffix in ("", ".wal", ".lock"):
        assert not (tmp_path / "data" / f"{FORMER_CACHE_DATABASE}{suffix}").exists()
    assert not (tmp_path / "data" / "blobs").exists()
    assert (tmp_path / "data" / "dem" / "dem_ign_a.tif").exists(), "a clean keeps the cache rows"
    assert (tmp_path / "data" / "dem" / "dem_ign_a.tif.json").exists()
    assert not (tmp_path / INTERNAL_DIRNAME).exists()
    assert not scratch_dir_for(project).exists()
    assert (tmp_path / "data" / "source" / "keep.csv").exists()


def test_workspace_clean_requires_group(monkeypatch, tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(
        "sys.argv",
        ["hmp", "workspace", "clean", "--workspace", str(tmp_path), "--yes"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_CONFIG
