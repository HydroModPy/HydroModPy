"""Unit tests for ``hmp workspace`` CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.cli import main
from hydromodpy.cli.helpers import EXIT_CONFIG


def _seed_workspace(root: Path) -> None:
    (root / "data" / "source").mkdir(parents=True)
    (root / "data" / "source" / "keep.csv").write_text("value\n1\n", encoding="utf-8")
    (root / "data" / "blobs").mkdir(parents=True)
    (root / "data" / "blobs" / "generated.bin").write_bytes(b"blob")
    (root / "data" / "cache.duckdb").write_bytes(b"duckdb")
    (root / "hydromodpy.duckdb").write_bytes(b"duckdb")
    (root / "simulations" / "run.zarr").mkdir(parents=True)
    (root / "exports").mkdir()
    (root / ".hmp").mkdir()
    (root / "projects" / "demo" / ".solver_scratch").mkdir(parents=True)
    (root / "projects" / "demo" / "figures").mkdir()


def test_workspace_clean_dry_run_keeps_files(monkeypatch, tmp_path: Path, capsys) -> None:
    _seed_workspace(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["hmp", "workspace", "clean", "--workspace", str(tmp_path), "--all"],
    )

    main()

    out = capsys.readouterr().out
    assert "Dry-run" in out
    assert (tmp_path / "hydromodpy.duckdb").exists()
    assert (tmp_path / "simulations").exists()
    assert (tmp_path / "data" / "cache.duckdb").exists()


def test_workspace_clean_all_deletes_generated_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _seed_workspace(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["hmp", "workspace", "clean", "--workspace", str(tmp_path), "--all", "--yes"],
    )

    main()

    assert not (tmp_path / "hydromodpy.duckdb").exists()
    assert not (tmp_path / "simulations").exists()
    assert not (tmp_path / "data" / "cache.duckdb").exists()
    assert not (tmp_path / "data" / "blobs").exists()
    assert not (tmp_path / "exports").exists()
    assert not (tmp_path / ".hmp").exists()
    assert not (tmp_path / "projects" / "demo" / ".solver_scratch").exists()
    assert not (tmp_path / "projects" / "demo" / "figures").exists()
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
