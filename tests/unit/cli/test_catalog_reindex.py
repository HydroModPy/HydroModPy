"""``hmp catalog reindex``: the index comes back from the run directories."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import catalog_path_for, runs_dir_for
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt


def _run(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.fixture
def project(tmp_path) -> Path:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    seal_run(root, "beta")
    return root


def test_reindex_builds_the_index_from_the_directories(monkeypatch, project, capsys) -> None:
    assert not catalog_path_for(project).exists()

    code = _run(monkeypatch, ["hmp", "catalog", "reindex", "--workspace", str(project)])

    assert code == 0
    out = capsys.readouterr().out
    assert "rebuilt: 2 run(s)" in out
    assert catalog_path_for(project).is_file()
    with Catalog(project) as catalog:
        assert set(catalog.list_simulations()["name"]) == {"alpha", "beta"}


def test_reindex_indexes_an_attempt_without_a_seal_as_a_case(monkeypatch, project, capsys) -> None:
    (runs_dir_for(project) / "beta" / RUN_MANIFEST_FILENAME).unlink()
    write_attempt(project, "runs/gamma", status="failed")

    code = _run(
        monkeypatch,
        ["hmp", "catalog", "reindex", "--workspace", str(project), "--format", "json"],
    )

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["full"] is True
    assert sorted(report["indexed"]) == ["runs/alpha", "runs/beta", "runs/gamma"]
    with Catalog(project) as catalog:
        cases = dict(catalog.backend.fetch_all("SELECT rel_dir, status FROM cases"))
    assert cases == {"runs/alpha": "completed", "runs/beta": "partial", "runs/gamma": "failed"}


def test_reindex_is_idempotent_on_the_command_line(monkeypatch, project, capsys) -> None:
    _run(monkeypatch, ["hmp", "catalog", "reindex", "--workspace", str(project)])
    capsys.readouterr()

    code = _run(
        monkeypatch,
        ["hmp", "catalog", "reindex", "--workspace", str(project), "--format", "json"],
    )

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert sorted(report["indexed"]) == ["runs/alpha", "runs/beta"]
    assert report["rows"]["simulations"] == 2


def test_reindex_incremental_writes_only_what_moved(monkeypatch, project, capsys) -> None:
    _run(monkeypatch, ["hmp", "catalog", "reindex", "--workspace", str(project)])
    capsys.readouterr()
    seal_run(project, "gamma")

    code = _run(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "reindex",
            "--incremental",
            "--workspace",
            str(project),
            "--format",
            "json",
        ],
    )

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["full"] is False
    assert report["indexed"] == ["runs/gamma"]


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
