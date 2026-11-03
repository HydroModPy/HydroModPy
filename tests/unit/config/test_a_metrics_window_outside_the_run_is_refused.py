"""A ``[metrics] window`` that shares no day with ``[simulation.time]`` is refused.

The run would be scored on nothing: no score, no message, and a calibrated
label on a run that was never compared. A window that overlaps the run partly
is accepted, the score reads what overlaps.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError

PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "metrics_window_test"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2020-12-31"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[metrics]
window = {{ start = "{start}", end = "{end}" }}
"""


def _write(tmp_path: Path, *, start: str, end: str) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(PROJECT_TOML.format(start=start, end=end), encoding="utf-8")
    return config_path


def test_a_window_before_the_run_is_refused_naming_both_periods(tmp_path: Path) -> None:
    config_path = _write(tmp_path, start="2001-01-01", end="2002-12-31")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    message = str(excinfo.value)
    assert "2001-01-01" in message and "2002-12-31" in message
    assert "2015-01-01" in message and "2020-12-31" in message
    assert "[metrics] window" in message


def test_a_window_after_the_run_is_refused(tmp_path: Path) -> None:
    config_path = _write(tmp_path, start="2021-01-01", end="2022-12-31")

    with pytest.raises(ConfigValidationError, match=r"\[metrics\] window"):
        HydroModPyConfig.from_toml(config_path)


def test_a_window_that_overlaps_the_run_partly_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, start="2012-01-01", end="2016-12-31")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.metrics.window.end.isoformat() == "2016-12-31"


def test_a_window_that_touches_the_last_day_of_the_run_loads(tmp_path: Path) -> None:
    config_path = _write(tmp_path, start="2020-12-31", end="2021-06-30")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.metrics.window.start.isoformat() == "2020-12-31"


def test_a_window_without_a_declared_run_is_left_alone(tmp_path: Path) -> None:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.replace('start_datetime = "2015-01-01"\n', "")
        .replace('end_datetime = "2020-12-31"\n', "")
        .format(start="2001-01-01", end="2002-12-31"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert "[metrics] window" not in str(excinfo.value)
