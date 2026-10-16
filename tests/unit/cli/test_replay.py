"""``hmp replay``: a run copied with its inputs, and the line that runs it again.

The verb publishes the run as a directory with ``inputs/``, then prints
``hmp run DIR/config.toml --frozen`` and the HydroModPy version the run was
sealed with. A run without a frozen configuration, a destination that holds
something and an unknown run are refused with their typed exit codes.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_GENERIC, EXIT_NOT_FOUND
from hydromodpy.results.publication import read_publication
from tests._helpers.cli_runner import CliRunner
from tests._helpers.sealed_run import RUN_NAME, seal_demo_run


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project holding one sealed monthly run named ``demo``, indexed, with its config."""
    root = tmp_path / "project"
    run_dir, _ = seal_demo_run(root)
    (run_dir / "config.toml").write_text('[site]\nname = "demo"\n', encoding="utf-8")
    return root


def _invoke(*args: str):
    return CliRunner().invoke(["replay", *args])


def test_the_copy_carries_its_inputs_and_the_replay_line_is_printed(
    project: Path, tmp_path: Path
) -> None:
    into = tmp_path / "replay"

    result = _invoke(RUN_NAME, "--into", str(into), "-w", str(project))

    assert result.exit_code == 0, result.stderr
    assert (into / "config.toml").is_file()
    assert read_publication(into).with_ == ["inputs"]
    command, version = result.stdout.splitlines()
    assert shlex.split(command) == ["hmp", "run", str(into.resolve() / "config.toml"), "--frozen"]
    sealed = json.loads((project / "runs" / RUN_NAME / "manifest.json").read_text())
    assert version == f"HydroModPy {sealed['identity']['hydromodpy_version']}"


def test_a_destination_that_holds_something_is_refused(project: Path, tmp_path: Path) -> None:
    into = tmp_path / "replay"
    into.mkdir()
    (into / "notes.txt").write_text("mine", encoding="utf-8")

    result = _invoke(RUN_NAME, "--into", str(into), "-w", str(project))

    assert result.exit_code == EXIT_GENERIC
    assert (into / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert not (into / "config.toml").exists()


def test_an_unknown_run_exits_not_found(project: Path, tmp_path: Path) -> None:
    result = _invoke("nowhere", "--into", str(tmp_path / "replay"), "-w", str(project))

    assert result.exit_code == EXIT_NOT_FOUND
    assert not (tmp_path / "replay").exists()


def test_the_destination_is_required(project: Path) -> None:
    result = _invoke(RUN_NAME, "-w", str(project))

    assert result.exit_code == 2
    assert "--into" in result.stderr


def test_a_run_without_a_frozen_config_is_refused_by_name(project: Path, tmp_path: Path) -> None:
    (project / "runs" / RUN_NAME / "config.toml").unlink()

    result = _invoke(RUN_NAME, "--into", str(tmp_path / "replay"), "-w", str(project))

    assert result.exit_code == EXIT_NOT_FOUND
    assert "config.toml" in result.stderr
    assert not (tmp_path / "replay").exists()
