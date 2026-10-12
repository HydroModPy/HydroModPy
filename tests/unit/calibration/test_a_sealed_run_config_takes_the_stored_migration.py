"""A calibration file frozen in ``runs/<name>/config.toml`` is migrated as a stored config.

``HydroModPyConfig.from_toml`` sends a sealed run file through the stored
migration before the one for user files. The calibration loader reads the same
files (a replay, ``--list-phases``) and must do the same: the user migration
logs a line telling the reader to run ``hmp doctor --fix-config`` on a file that
no command rewrites.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.core.state.paths import RUNS_DIRNAME

pytestmark = pytest.mark.unit

_TOML = """\
[calibration]
method = "grid"
objective = "nse"

[calibration.parameters.K]
bounds = [1e-8, 1e-2]
transform = "log"

[simulation.results.budget]
spatial_fields = true
"""


def _migration_lines(path: Path, caplog) -> list[str]:
    with caplog.at_level(logging.INFO):
        cfg, raw = load_toml_calibration(path)
    assert cfg.method == "grid"
    assert "budget" not in raw["simulation"]["results"]
    return [r.getMessage() for r in caplog.records if "migrated" in r.getMessage()]


def test_a_sealed_run_file_goes_through_the_stored_migration(tmp_path: Path, caplog) -> None:
    run_dir = tmp_path / RUNS_DIRNAME / "nancon"
    run_dir.mkdir(parents=True)
    sealed = run_dir / "config.toml"
    sealed.write_text(_TOML, encoding="utf-8")

    lines = _migration_lines(sealed, caplog)

    assert any("removed since the run was stored" in line for line in lines)
    assert not any("hmp doctor" in line for line in lines)


def test_a_user_file_keeps_the_user_migration(tmp_path: Path, caplog) -> None:
    user = tmp_path / "calibration.toml"
    user.write_text(_TOML, encoding="utf-8")

    lines = _migration_lines(user, caplog)

    assert any("hmp doctor --fix-config" in line for line in lines)
    assert not any("removed since the run was stored" in line for line in lines)
