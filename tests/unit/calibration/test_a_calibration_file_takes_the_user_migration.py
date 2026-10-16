"""A calibration file goes through the migration of user files when it is read."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import load_toml_calibration

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


def test_a_user_file_keeps_the_user_migration(tmp_path: Path, caplog) -> None:
    user = tmp_path / "calibration.toml"
    user.write_text(_TOML, encoding="utf-8")

    lines = _migration_lines(user, caplog)

    assert any("rename them in" in line for line in lines)
