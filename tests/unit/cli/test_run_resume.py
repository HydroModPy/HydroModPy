"""``hmp run --resume REF`` resolves the snapshot and resumes by run name."""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

import pytest

from hydromodpy.cli.commands import run as run_cmd
from hydromodpy.results.catalog import Catalog


def _args(**kw) -> argparse.Namespace:
    base = {
        "from_step": None,
        "until_step": None,
        "no_display": True,
        "no_parallel": False,
        "dry_run": True,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _seed_run(workspace: Path, name: str) -> str:
    sid = str(uuid.uuid4())
    with Catalog(workspace) as catalog:
        catalog.register_simulation(
            sid, project="cheze", solver="modflow6", name=name, config={"workflow": {"mode": "x"}}
        )
    return sid


def test_resume_from_ref_resolves_snapshot_and_resumes_by_name(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed_run(workspace, "cheze_baseline")

    calls: dict = {}

    class _FakeProject:
        def __init__(self, snapshot):
            calls["snapshot"] = snapshot

        def simulate(self, **kw):
            calls["simulate"] = kw
            return None

    monkeypatch.setattr("hydromodpy.project.Project", _FakeProject)
    monkeypatch.chdir(workspace)

    run_cmd._resume_from_ref("cheze_baseline", args=_args())

    # config sourced from the snapshot, resumed under the run's own name
    assert calls["snapshot"]["workflow"]["mode"] == "x"
    assert calls["simulate"]["resume"] == "cheze_baseline"
    assert calls["simulate"]["name"] == "cheze_baseline"


def test_resume_from_ref_unknown_ref_exits_not_found(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed_run(workspace, "exists")
    monkeypatch.chdir(workspace)
    with pytest.raises(SystemExit) as exc:
        run_cmd._resume_from_ref("nope", args=_args())
    assert exc.value.code != 0


def test_run_without_config_or_resume_errors(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_cmd.run(_args(config=None, resume=None))
    assert exc.value.code != 0
