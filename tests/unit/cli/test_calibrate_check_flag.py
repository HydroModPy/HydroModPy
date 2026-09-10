"""``hmp calibrate --check`` refuses before the solver, not during it.

A calibration is hours of solver time, and the checks used to fire where they
sat: a typo in a parameter path at the first trial, a missing geometry when the
criterion first ran. Each one cost the run that had already happened. The flag
runs them all, solves nothing, and exits on the config code when anything is
wrong so a script can gate on it.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import pytest

from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.cli.helpers import EXIT_CONFIG

_TEMPLATE = textwrap.dedent(
    """
    [workspace]
    project_root = "PROJECT_ROOT"

    [workflow]
    mode = "calibration"

    [simulation.time]
    start_datetime = "2000-01-01"
    end_datetime = "2000-12-31"
    step_value = 1
    step_unit = "day"

    [geographic]
    source_mode = "synthetic"

    [flow.param.K.field]
    id = "K"
    kind = "homogeneous"
    unit = "m/s"
    value = 6.4e-5

    [calibration]
    method = "grid"
    max_iter = 4

    [calibration.parameters.K]
    bounds = [1e-7, 1e-3]
    path = "PARAM_PATH"
    """
)


def _write(tmp_path: Path, *, param_path: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text(
        _TEMPLATE.replace("PROJECT_ROOT", str(tmp_path)).replace("PARAM_PATH", param_path),
        encoding="utf-8",
    )
    return path


def _check(path: Path) -> None:
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=True, list_phases=False, phase=None, profile=None)
    )


def test_a_sound_file_passes_and_solves_nothing(tmp_path, capsys) -> None:
    _check(_write(tmp_path, param_path="flow.param.K.field.value"))

    assert "ready to run" in capsys.readouterr().err


def test_a_path_the_configuration_does_not_carry_exits_on_the_config_code(tmp_path, capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        _check(_write(tmp_path, param_path="flow.param.Kh.field.value"))

    assert caught.value.code == EXIT_CONFIG
    assert "flow.param.Kh.field.value" in capsys.readouterr().err


def test_the_summary_counts_what_it_found(tmp_path, capsys) -> None:
    with pytest.raises(SystemExit):
        _check(_write(tmp_path, param_path="flow.param.Kh.field.value"))

    assert "1 error(s)" in capsys.readouterr().err
