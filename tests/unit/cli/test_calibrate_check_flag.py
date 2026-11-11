"""``hmp check`` refuses a calibration before the solver, not during it.

A calibration is hours of solver time, and the checks used to fire where they
sat: a typo in a parameter path at the first trial, a missing geometry when the
criterion first ran. Each one cost the run that had already happened. The check
runs them all, solves nothing, and exits on the config code when anything is
wrong so a script can gate on it. It also says which published method the file
runs and where it departs from it. ``hmp calibrate --check`` was its old name.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG
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


def test_a_sound_file_passes_and_solves_nothing(tmp_path) -> None:
    result = _check(_write(tmp_path, param_path="flow.param.K.field.value"))

    assert result.exit_code == 0, result.stderr
    assert "OK:" in result.stdout


def test_a_path_the_configuration_does_not_carry_exits_on_the_config_code(tmp_path) -> None:
    result = _check(_write(tmp_path, param_path="flow.param.Kh.field.value"))

    assert result.exit_code == EXIT_CONFIG
    assert "flow.param.Kh.field.value" in result.stderr
    assert "Config invalid:" in result.stderr


def test_a_refused_calibration_says_its_diagnostic_in_the_machine_output(tmp_path) -> None:
    path = _write(tmp_path, param_path="flow.param.Kh.field.value")

    result = CliRunner().invoke(["check", str(path), "--format", "json"])

    data = json.loads(result.stdout)["data"]
    assert result.exit_code == EXIT_CONFIG
    assert data["ok"] is False
    refused = [item for item in data["diagnostics"] if item["severity"] == "error"]
    assert refused
    assert any("flow.param.Kh.field.value" in item["loc"] + item["msg"] for item in refused)


def test_hmp_calibrate_has_no_check_flag_any_more(tmp_path) -> None:
    result = CliRunner().invoke(["calibrate", str(tmp_path / "calib.toml"), "--check"])

    assert result.exit_code == 2


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


def test_a_named_method_is_announced_and_its_references_wait_for_verbose(tmp_path) -> None:
    path = tmp_path / "calib.toml"
    path.write_text(_PROTOCOL.replace("PROJECT_ROOT", tmp_path.as_posix()), encoding="utf-8")
    (tmp_path / "streams.gpkg").write_bytes(b"")

    normal = _check(path)
    verbose = _check(path, verbosity="verbose")

    assert normal.exit_code == 0, normal.stderr
    assert "matching_hydrographic_network" in normal.stderr
    assert "OK:" in normal.stdout
    assert "10.5194/hess-27-3221-2023" not in normal.stderr
    assert "stage 1:" not in normal.stderr
    assert "cite: " in verbose.stderr
    assert "10.5194/hess-27-3221-2023" in verbose.stderr
    assert "stage 1:" in verbose.stderr
    assert "OK:" in verbose.stdout


def test_quiet_prints_nothing_for_a_sound_file(tmp_path) -> None:
    path = tmp_path / "calib.toml"
    path.write_text(_PROTOCOL.replace("PROJECT_ROOT", tmp_path.as_posix()), encoding="utf-8")
    (tmp_path / "streams.gpkg").write_bytes(b"")

    result = _check(path, verbosity="quiet")

    assert result.exit_code == 0
    assert result.stderr == ""


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


def test_a_run_of_one_year_is_told_its_spin_up_year_is_scored(tmp_path) -> None:
    """The protocol drops its default window silently; the check says so."""
    result = _check(_protocol_file(tmp_path))

    assert "stage 2 scores the whole run, spin-up year included" in result.stderr
    assert "ends on 2000-12-31, within one year of its start 2000-01-01" in result.stderr
    assert "OK:" in result.stdout


def test_a_run_past_its_first_year_gets_no_such_line(tmp_path) -> None:
    result = _check(_protocol_file(tmp_path, end="2002-12-31"))

    assert "spin-up year included" not in result.stderr


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


def test_only_the_departures_print_at_the_normal_verbosity(tmp_path) -> None:
    """The default fill is the paper's; tau, heads, the cut and the veto are not."""
    printed = _check(_protocol_file(tmp_path, end="2002-12-31")).stderr
    departures = [line for line in printed.splitlines() if "  differs from the paper" in line]
    # The four above, the two heads keys with the value in force, and the two
    # departures that hold while the file writes no steady_window and no scoring window.
    assert len(departures) == 8
    assert any("on map.heads.radius" in line and "value in force" in line for line in departures)
    tau_line = next(line for line in departures if "on model.seepage_threshold" in line)
    assert "this file sets" not in tau_line
    assert any("on map.drawn_by" in line for line in departures)
    assert any("on map.clip_to_catchment" in line for line in departures)
    assert any("on verdict.max_catchment_mismatch" in line for line in departures)
    assert "dem_correc_type" not in printed


def test_a_departure_no_key_brings_back_is_named_and_said_in_verbose(tmp_path) -> None:
    path = _protocol_file(tmp_path, end="2002-12-31")

    named = next(
        line for line in _check(path).stderr.splitlines() if "always differs from the paper" in line
    )
    verbose = _check(path, verbosity="verbose").stderr

    assert "d_os_support" in named
    assert "steady_recharge_window" not in named, "a steady_window brings it back"
    assert "always differs from the paper on d_os_support:" in verbose
    assert "reads the paper on d_os_support" not in verbose


def test_a_launch_says_where_it_departs_before_anything_is_solved(tmp_path, caplog) -> None:
    from hydromodpy.calibration.preflight import refuse_what_the_preflight_refuses
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    path = _protocol_file(tmp_path, end="2002-12-31")
    config = HydroModPyConfig.from_toml(path)

    with caplog.at_level("INFO"):
        refuse_what_the_preflight_refuses(config, source=path)

    assert "protocol: matching_hydrographic_network@1.3" in caplog.text
    assert "differs from the paper on map.drawn_by" in caplog.text
    assert "always differs from the paper on:" in caplog.text


def test_a_value_written_equal_to_the_paper_is_not_a_departure(tmp_path) -> None:
    path = _protocol_file(tmp_path, end="2002-12-31")
    text = path.read_text(encoding="utf-8").replace(
        'map.complete = "streams.gpkg"',
        'map.complete = "streams.gpkg"\nmodel.seepage_threshold = 0.0\n'
        'map.drawn_by = "crossing"\n'
        'model.neighbours = "D8"\n'
        "map.clip_to_catchment = false\n"
        "[calibration.outputs.seepage_network.verdict]\n"
        "max_catchment_mismatch = false",
    )
    path.write_text(text, encoding="utf-8")

    printed = _check(path).stderr
    verbose = _check(path, verbosity="verbose").stderr

    differing = [line for line in printed.splitlines() if "  differs from the paper" in line]
    assert {line.split(" on ")[1].split(":")[0] for line in differing} == {
        "steady_recharge_window",
        "spin_up_year",
    }
    assert "as the paper on model.neighbours" in verbose
    assert "this file sets 0.0" in verbose


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

    # Only a pre-release of 2.0 wrote steady_engine_options: the refusal names the old
    # key and the way to its new name, the doctor of 2.0, which writes steady_method_options.
    assert result.exit_code == EXIT_CONFIG, result.stderr
    assert "calibration.protocol.steady_engine_options" in result.stderr
    assert "written by a pre-release of 2.0" in result.stderr
    assert "hmp doctor --fix-config" in result.stderr


def test_a_phase_two_option_its_method_refuses_is_named_before_phase_one_runs(
    tmp_path,
) -> None:
    """It used to pass the check and fail when phase two started."""
    path = _protocol_file(tmp_path, end="2002-12-31")
    text = path.read_text(encoding="utf-8").replace(
        'protocol = "matching_hydrographic_network"',
        'protocol = { name = "matching_hydrographic_network", '
        "transient_method_options = { sweep_points = 7 } }",
    )
    path.write_text(text, encoding="utf-8")

    result = _check(path)

    assert result.exit_code == EXIT_CONFIG
    printed = result.stderr
    assert "transient_method_options" in printed
    assert "'scipy_nelder_mead' does not take sweep_points" in printed
