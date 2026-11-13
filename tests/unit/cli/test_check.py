"""``hmp check`` reads a configuration and refuses what would fail later, solving nothing.

A calibration is hours of solver time, so a typo in a parameter path or a missing geometry must stop
the command first. A refusal exits on the config code (14), a missing file on the not-found code (10).
For a published calibration protocol it also says where the file departs from the published method.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG
from tests._helpers.cli_runner import CliRunner

pytestmark = pytest.mark.fast

CALIBRATION_HEAD = """
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
"""

GRID_SEARCH = (
    CALIBRATION_HEAD
    + """
[calibration]
method = "grid"
max_trials = 4
method_options = { points_per_dim = 4 }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "PARAM_PATH"
"""
)

PROTOCOL = (
    CALIBRATION_HEAD
    + """
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

SIMULATION = """\
[workspace]

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

[simulation]
name = "baseline"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "transient"

"""

TWO_EXPORTS = '[[export]]\nvariables = "discharge"\n\n[[export]]\nvariables = ["discharge"]\n'

REFUSALS = [
    pytest.param("not = [valid", "Invalid TOML syntax:", id="invalid toml"),
    pytest.param(
        SIMULATION + '[[display.figure]]\nvariable = "head"\ntime = "2005-01-01"\n',
        "display.figure[0].time: 2005-01-01 is outside the record",
        id="date outside the record",
    ),
    pytest.param(
        SIMULATION + TWO_EXPORTS,
        "export[0] and export[1] both write discharge.csv",
        id="two blocks write one file",
    ),
]


def check_file(path: Path, *flags: str):
    return CliRunner().invoke(["check", str(path), *flags])


def grid_search_file(tmp_path: Path, *, param_path: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text(GRID_SEARCH.replace("PARAM_PATH", param_path), encoding="utf-8")
    return path


def protocol_file(tmp_path: Path, *, end: str = "2000-12-31", geographic: str = "") -> Path:
    text = PROTOCOL.replace('end_datetime = "2000-12-31"', f'end_datetime = "{end}"')
    text = text.replace('source_mode = "synthetic"', f'source_mode = "synthetic"\n{geographic}')
    path = tmp_path / "calib.toml"
    path.write_text(text, encoding="utf-8")
    (tmp_path / "streams.gpkg").write_bytes(b"")
    return path


def set_protocol(path: Path, protocol: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('protocol = "matching_hydrographic_network"', f"protocol = {protocol}"),
        encoding="utf-8",
    )


def test_missing_file(tmp_path) -> None:
    result = check_file(tmp_path / "gone.toml")

    assert result.exit_code == 10
    assert "File not found" in result.stderr


@pytest.mark.parametrize(("text", "message"), REFUSALS)
def test_refusals(tmp_path, text, message) -> None:
    path = tmp_path / "project.toml"
    path.write_text(text, encoding="utf-8")

    result = check_file(path)

    assert result.exit_code == 14
    assert message in result.stderr


def test_retired_mode(tmp_path) -> None:
    config = tmp_path / "comparison.toml"
    config.write_text('[workflow]\nmode = "comparison"\n', encoding="utf-8")

    result = check_file(config)

    assert result.exit_code == 14
    assert f"Config invalid: {config.resolve()}" in result.stderr
    assert "hmp diff" in result.stderr


def test_sites_project_passes(tmp_path) -> None:
    from tests.unit.project.launch.test_plan import write_sites_project

    project = write_sites_project(tmp_path)

    checked = check_file(project / "project.toml")
    planned = CliRunner().invoke(["run", str(project / "project.toml"), "--dry-run", "-q"])

    assert checked.exit_code == 0, checked.stderr
    assert f"OK: {project / 'project.toml'}" in checked.stdout
    assert planned.exit_code == 0, planned.stderr
    assert "4 cases (" in planned.stdout


def test_sites_project_error_cell(tmp_path) -> None:
    from tests.unit.project.launch.test_plan import write_sites_project

    project = write_sites_project(tmp_path, k_cells=("5e-5", "not_a_number"))

    result = check_file(project / "project.toml")

    assert result.exit_code == 14
    assert "sites.csv:3 column k -> flow.param.K.field.value" in result.stderr


def test_unreadable_recipe_named(tmp_path) -> None:
    from tests.unit.project.launch.test_plan import write_sites_project

    project = write_sites_project(tmp_path)
    (project / "bad.toml").write_text('base_config = "project.toml"\n[flow\n', encoding="utf-8")
    project_toml = project / "project.toml"
    project_toml.write_text(
        project_toml.read_text(encoding="utf-8").replace(
            "[sites.recipes]\n", '[sites.recipes]\nbad = "bad.toml"\n'
        ),
        encoding="utf-8",
    )

    result = check_file(project_toml)

    assert result.exit_code == 14
    assert "Traceback" not in result.stderr
    assert "[sites.recipes] bad: " in result.stderr and "invalid TOML" in result.stderr


def test_full_template_refused(tmp_path) -> None:
    template = tmp_path / "full.toml"
    assert CliRunner().invoke(["config", "template", "--to", str(template)]).exit_code == 0

    checked = check_file(template)

    output = checked.stderr + checked.stdout
    assert checked.exit_code != 0
    assert "error geographic.catchment:" in output
    assert "geographic.catchment.kind is required" in output
    assert "crossings" not in output
    assert "to_fill" not in output


def test_machine_output_keys(tmp_path) -> None:
    path = tmp_path / "draft.toml"
    path.write_text('[flow]\nflow_regime = "steady"\n', encoding="utf-8")

    result = check_file(path, "--format", "json", "--partial")

    data = json.loads(result.stdout)["data"]
    assert set(data) == {"ok", "diagnostics", "workspace"}
    for item in data["diagnostics"]:
        assert {"pointer", "loc", "msg", "type", "code", "severity", "help", "phrase"} <= set(item)


def test_unknown_parameter_path(tmp_path) -> None:
    result = check_file(grid_search_file(tmp_path, param_path="flow.param.Kh.field.value"))

    assert result.exit_code == EXIT_CONFIG
    assert "flow.param.Kh.field.value" in result.stderr
    assert "Config invalid:" in result.stderr


def test_quiet_keeps_findings(tmp_path) -> None:
    path = grid_search_file(tmp_path, param_path="flow.param.Kh.field.value")

    result = check_file(path, "--verbosity", "quiet")

    assert result.exit_code == EXIT_CONFIG
    assert "flow.param.Kh.field.value" in result.stderr


def test_breach_departure_announced(tmp_path) -> None:
    result = check_file(protocol_file(tmp_path, geographic='dem_correc_type = "breach"'))

    lines = result.stderr.splitlines()
    line = next(line for line in lines if "differs from the paper on dem_correc_type" in line)
    assert line.endswith("this file sets 'breach'")


def test_unwritten_dem_conditioning(tmp_path) -> None:
    result = check_file(protocol_file(tmp_path), "--verbosity", "verbose")

    lines = result.stderr.splitlines()
    line = next(line for line in lines if "as the paper on dem_correc_type" in line)
    assert "this file sets" not in line


def test_recipe_options_not_flagged(tmp_path) -> None:
    # Seven sweep points, one per cent on K and the spin-up window are what the recipe runs.
    path = protocol_file(tmp_path, end="2002-12-31")
    set_protocol(
        path,
        '{ name = "matching_hydrographic_network", steady_precision = 0.01, '
        "transient_max_trials = 30, steady_method_options = { sweep_points = 7 }, "
        'window = { start = "2001-01-01", end = "2002-12-31" } }',
    )

    printed = check_file(path).stderr
    verbose = check_file(path, "--verbosity", "verbose").stderr

    away = [line for line in printed.splitlines() if "option away from the recipe" in line]
    assert away == ["  option away from the recipe: transient_max_trials = 30 (recipe: 120)"]
    assert "option written as the recipe runs it: steady_method_options" in verbose
    assert "option written as the recipe runs it: steady_precision = 0.01" in verbose
    assert "option written as the recipe runs it: window" in verbose


def test_old_key_refused(tmp_path) -> None:
    path = protocol_file(tmp_path, end="2002-12-31")
    set_protocol(
        path,
        '{ name = "matching_hydrographic_network", steady_engine_options = { sweep_points = 5 } }',
    )

    result = check_file(path)

    # Only a pre-release wrote steady_engine_options: the refusal names the old key and says the
    # file is not rewritten.
    assert result.exit_code == EXIT_CONFIG, result.stderr
    assert "calibration.protocol.steady_engine_options" in result.stderr
    assert "written by a pre-release of 2.0" in result.stderr
    assert "This version does not rewrite the file." in result.stderr
