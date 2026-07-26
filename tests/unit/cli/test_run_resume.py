"""``hmp run --resume REF`` replays the config frozen in the run directory."""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

import pytest

from hydromodpy.cli.commands import run as run_cmd
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME

FROZEN_TOML = '[workflow]\nmode = "simulation"\n'


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


def _seed_run(workspace: Path, name: str, *, freeze_config: bool = True) -> str:
    sid = str(uuid.uuid4())
    with Catalog(workspace) as catalog:
        catalog.register_simulation(
            sid, project="cheze", solver="modflow6", name=name, config={"workflow": {"mode": "x"}}
        )
        run_dir = catalog.run_dir_for(sid)
    if freeze_config:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / RUN_CONFIG_FILENAME).write_text(FROZEN_TOML, encoding="utf-8")
    return sid


def test_resume_from_ref_replays_the_frozen_run_config(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed_run(workspace, "cheze_baseline")

    calls: dict = {}

    def _fake_run_toml(config_path: Path, *, args: argparse.Namespace) -> None:
        calls["config_path"] = config_path
        calls["resume"] = args.resume

    monkeypatch.setattr(run_cmd, "_run_toml", _fake_run_toml)
    monkeypatch.chdir(workspace)

    run_cmd._resume_from_ref("cheze_baseline", args=_args(resume="cheze_baseline"))

    # The run's own frozen config drives the replay, under the run's name.
    assert calls["config_path"] == workspace / "runs" / "cheze_baseline" / RUN_CONFIG_FILENAME
    assert calls["config_path"].read_text(encoding="utf-8") == FROZEN_TOML
    assert calls["resume"] == "cheze_baseline"


def test_resume_from_ref_accepts_a_sim_id_prefix(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sid = _seed_run(workspace, "cheze_baseline")

    calls: dict = {}
    monkeypatch.setattr(
        run_cmd,
        "_run_toml",
        lambda config_path, *, args: calls.update(resume=args.resume, config_path=config_path),
    )
    monkeypatch.chdir(workspace)

    run_cmd._resume_from_ref(sid[:8], args=_args(resume=sid[:8]))

    # The journal is keyed by the run name, so the reference is resolved to it.
    assert calls["resume"] == "cheze_baseline"


def test_resume_from_ref_without_frozen_config_exits_not_found(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed_run(workspace, "cheze_baseline", freeze_config=False)
    monkeypatch.chdir(workspace)

    with pytest.raises(SystemExit) as exc:
        run_cmd._resume_from_ref("cheze_baseline", args=_args())
    assert exc.value.code != 0


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
