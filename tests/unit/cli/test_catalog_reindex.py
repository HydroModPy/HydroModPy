"""``hmp catalog reindex``: the index comes back from the run directories."""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import catalog_path_for, runs_dir_for
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.manifest import RUN_MANIFEST_FILENAME


def _run(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _seal_run(catalog: Catalog, name: str) -> str:
    sid = str(uuid.uuid4())
    registration = catalog.register_simulation(
        sid,
        project="demo",
        solver="modflow6",
        name=name,
        n_cells=32,
        n_layers=1,
    )
    if registration.zarr is not None:
        registration.zarr.close()
    catalog.finalize(sid, status="completed", duration_s=1.0)
    return sid


@pytest.fixture
def project(tmp_path) -> Path:
    root = tmp_path / "demo"
    root.mkdir()
    (root / "project.toml").write_text("[workspace]\nproject_root = '.'\n")
    with Catalog(root) as catalog:
        _seal_run(catalog, "alpha")
        _seal_run(catalog, "beta")
    return root


def test_reindex_rebuilds_a_deleted_index(monkeypatch, project, capsys) -> None:
    catalog_path_for(project).unlink()

    code = _run(monkeypatch, ["hmp", "catalog", "reindex", "--workspace", str(project)])

    assert code == 0
    out = capsys.readouterr().out
    assert "indexed 2 run(s)" in out
    assert catalog_path_for(project).is_file()
    with Catalog(project, read_only=True) as catalog:
        assert set(catalog.list_simulations()["name"]) == {"alpha", "beta"}


def test_reindex_reports_an_unsealed_run(monkeypatch, project, capsys) -> None:
    (runs_dir_for(project) / "beta" / RUN_MANIFEST_FILENAME).unlink()

    code = _run(
        monkeypatch,
        ["hmp", "catalog", "reindex", "--workspace", str(project), "--format", "json"],
    )

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["indexed"] == ["alpha"]
    assert report["skipped"][0]["run"] == "beta"


def test_reindex_is_idempotent_on_the_command_line(monkeypatch, project, capsys) -> None:
    _run(monkeypatch, ["hmp", "catalog", "reindex", "--workspace", str(project)])
    capsys.readouterr()

    code = _run(
        monkeypatch,
        ["hmp", "catalog", "reindex", "--workspace", str(project), "--format", "json"],
    )

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["indexed"] == ["alpha", "beta"]
    assert report["rows"]["simulations"] == 2


def test_reindex_appears_in_the_catalog_help(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "catalog", "--help"])

    assert code == 0
    assert "reindex" in capsys.readouterr().out


def test_adopt_is_gone(monkeypatch, project) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "adopt", str(runs_dir_for(project) / "alpha")],
    )

    assert code == 2
