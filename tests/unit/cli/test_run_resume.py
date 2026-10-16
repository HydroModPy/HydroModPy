"""``hmp run --resume REF`` replays the config frozen in the run directory.

REF is a case name read on disk, never through the index: a bare name is its
latest version, a versioned name is that directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hydromodpy.cli.commands import run as run_cmd
from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from tests._helpers.sealed_runs import make_project, write_attempt

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


def _seed_run(
    workspace: Path, name: str, *, freeze_config: bool = True, text: str = FROZEN_TOML
) -> Path:
    """Write a failed attempt of *name* on disk, with its frozen config when asked."""
    make_project(workspace)
    run_dir = write_attempt(workspace, f"runs/{name}", status="failed", attempt=1)
    if freeze_config:
        (run_dir / RUN_CONFIG_FILENAME).write_text(text, encoding="utf-8")
    return run_dir


def test_resume_from_ref_replays_the_frozen_run_config(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
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


def test_a_bare_name_resumes_its_latest_version_and_a_versioned_name_that_one(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "ws"
    _seed_run(workspace, "cheze_baseline", text="# v1\n" + FROZEN_TOML)
    _seed_run(workspace, "cheze_baseline.v2", text="# v2\n" + FROZEN_TOML)

    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        run_cmd,
        "_run_toml",
        lambda config_path, *, args: calls.append((config_path, args.resume)),
    )
    monkeypatch.chdir(workspace)

    run_cmd._resume_from_ref("cheze_baseline", args=_args(resume="cheze_baseline"))
    run_cmd._resume_from_ref("cheze_baseline.v2", args=_args(resume="cheze_baseline.v2"))

    assert [name for _path, name in calls] == ["cheze_baseline.v2", "cheze_baseline.v2"]
    assert all(path.read_text(encoding="utf-8").startswith("# v2") for path, _name in calls)


def test_resume_from_ref_without_frozen_config_exits_not_found(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    _seed_run(workspace, "cheze_baseline", freeze_config=False)
    monkeypatch.chdir(workspace)

    with pytest.raises(SystemExit) as exc:
        run_cmd._resume_from_ref("cheze_baseline", args=_args())
    assert exc.value.code != 0


def test_resume_from_ref_unknown_ref_exits_not_found(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
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


def test_force_is_rejected_outside_the_simulation_workflow(tmp_path, monkeypatch, capsys):
    """Only the simulation workflow skips an identical run, so only it accepts --force."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = workspace / "overview.toml"
    config.write_text('[workflow]\nmode = "overview"\n', encoding="utf-8")
    monkeypatch.chdir(workspace)

    with pytest.raises(SystemExit) as exit_info:
        run_cmd._run_toml(config, args=_args(resume=None, force=True, dry_run=False))

    assert exit_info.value.code == EXIT_CONFIG
    assert "--force is only supported for the 'simulation' workflow" in capsys.readouterr().err
