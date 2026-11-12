"""``hmp check`` refuses a calibration before the solver, not during it.

A calibration is hours of solver time, and the checks used to fire where they
sat: a typo in a parameter path at the first trial, a missing geometry when the
criterion first ran. Each one cost the run that had already happened. The check
runs them all, solves nothing, and exits on the config code when anything is
wrong so a script can gate on it. It also says which published method the file
runs and where it departs from it. ``hmp calibrate --check`` was its old name.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from hydromodpy.cli.exit_codes import EXIT_CONFIG
from tests._helpers.cli_runner import CliRunner

_TEMPLATE = textwrap.dedent(
    """
    [workspace]

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
    max_trials = 4
    method_options = { points_per_dim = 4 }

    [calibration.parameters.K]
    bounds = [1e-7, 1e-3]
    path = "PARAM_PATH"
    """
)


def _write(tmp_path: Path, *, param_path: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text(
        _TEMPLATE.replace("PROJECT_ROOT", tmp_path.as_posix()).replace("PARAM_PATH", param_path),
        encoding="utf-8",
    )
    return path


def _check(path: Path, verbosity: str | None = None):
    argv = ["check", str(path)]
    if verbosity is not None:
        argv += ["--verbosity", verbosity]
    return CliRunner().invoke(argv)


def test_a_path_the_configuration_does_not_carry_exits_on_the_config_code(tmp_path) -> None:
    result = _check(_write(tmp_path, param_path="flow.param.Kh.field.value"))

    assert result.exit_code == EXIT_CONFIG
    assert "flow.param.Kh.field.value" in result.stderr
    assert "Config invalid:" in result.stderr


_PROTOCOL = textwrap.dedent(
    """
    [workspace]

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

    [flow.param.Sy.field]
    id = "Sy"
    kind = "homogeneous"
    unit = "-"
    value = 0.05

    [calibration]
    protocol = "matching_hydrographic_network"

    [calibration.parameters.K]
    bounds = [1e-7, 1e-3]
    search_space = "log"

    [calibration.parameters.Sy]
    bounds = [5e-3, 0.35]
    search_space = "log"
    units = "-"

    [calibration.outputs.seepage_network]
    support = "network"
    map.complete = "streams.gpkg"

    [[data.hydrometry.sources]]
    station_ids = ["G1"]
    """
)


def test_quiet_keeps_the_findings(tmp_path) -> None:
    result = _check(_write(tmp_path, param_path="flow.param.Kh.field.value"), verbosity="quiet")

    assert result.exit_code == EXIT_CONFIG
    assert "flow.param.Kh.field.value" in result.stderr


def _protocol_file(tmp_path: Path, *, end: str = "2000-12-31", geographic: str = "") -> Path:
    path = tmp_path / "calib.toml"
    text = _PROTOCOL.replace("PROJECT_ROOT", tmp_path.as_posix()).replace(
        'end_datetime = "2000-12-31"', f'end_datetime = "{end}"'
    )
    text = text.replace('source_mode = "synthetic"', f'source_mode = "synthetic"\n{geographic}')
    path.write_text(text, encoding="utf-8")
    (tmp_path / "streams.gpkg").write_bytes(b"")
    return path


def test_a_breach_written_under_geographic_is_announced(tmp_path) -> None:
    result = _check(_protocol_file(tmp_path, geographic='dem_correc_type = "breach"'))

    lines = result.stderr.splitlines()
    line = next(line for line in lines if "differs from the paper on dem_correc_type" in line)
    assert line.endswith("this file sets 'breach'")


def test_an_unwritten_dem_conditioning_is_not_claimed_by_the_file(tmp_path) -> None:
    result = _check(_protocol_file(tmp_path), verbosity="verbose")

    lines = result.stderr.splitlines()
    line = next(line for line in lines if "as the paper on dem_correc_type" in line)
    assert "this file sets" not in line


def test_options_written_as_the_recipe_runs_them_are_not_away_from_it(tmp_path) -> None:
    """Seven sweep points, one per cent on K and the spin-up window are what the recipe runs."""
    path = _protocol_file(tmp_path, end="2002-12-31")
    text = path.read_text(encoding="utf-8").replace(
        'protocol = "matching_hydrographic_network"',
        'protocol = { name = "matching_hydrographic_network", steady_precision = 0.01, '
        "transient_max_trials = 30, steady_method_options = { sweep_points = 7 }, "
        'window = { start = "2001-01-01", end = "2002-12-31" } }',
    )
    path.write_text(text, encoding="utf-8")

    printed = _check(path).stderr
    verbose = _check(path, verbosity="verbose").stderr

    away = [line for line in printed.splitlines() if "option away from the recipe" in line]
    assert away == ["  option away from the recipe: transient_max_trials = 30 (recipe: 120)"]
    assert "option written as the recipe runs it: steady_method_options" in verbose
    assert "option written as the recipe runs it: steady_precision = 0.01" in verbose
    assert "option written as the recipe runs it: window" in verbose


def test_an_old_key_is_refused_with_its_new_name(tmp_path) -> None:
    path = _protocol_file(tmp_path, end="2002-12-31")
    text = path.read_text(encoding="utf-8").replace(
        'protocol = "matching_hydrographic_network"',
        'protocol = { name = "matching_hydrographic_network", '
        "steady_engine_options = { sweep_points = 5 } }",
    )
    path.write_text(text, encoding="utf-8")

    result = _check(path)

    # Only a pre-release wrote steady_engine_options: the refusal names the old
    # key and says the file is not rewritten.
    assert result.exit_code == EXIT_CONFIG, result.stderr
    assert "calibration.protocol.steady_engine_options" in result.stderr
    assert "written by a pre-release of 2.0" in result.stderr
    assert "This version does not rewrite the file." in result.stderr
