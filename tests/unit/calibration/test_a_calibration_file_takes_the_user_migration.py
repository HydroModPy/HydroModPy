"""A calibration file goes through the migration of user files when it is read."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

pytestmark = pytest.mark.unit

_TOML = """\
[calibration]
method = "grid"
objective = "nse"

[calibration.parameters.K]
bounds = [1e-8, 1e-2]
search_space = "log"

[simulation.results.budget]
spatial_fields = true
"""


def test_a_user_file_keeps_the_user_migration(tmp_path: Path) -> None:
    user = tmp_path / "calibration.toml"
    user.write_text(_TOML, encoding="utf-8")

    with pytest.warns(ConfigKeyRenamedWarning, match="hmp doctor --fix-config"):
        cfg, raw = load_toml_calibration(user)

    assert cfg.method == "grid"
    assert "budget" not in raw["simulation"]["results"]
