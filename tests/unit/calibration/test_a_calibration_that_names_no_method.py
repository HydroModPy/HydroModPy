"""A calibration that names no method gets the one its criteria call for.

A phase, or a calibration run in one stage, that does not write ``method`` runs
``bisection`` when it moves one parameter in log space and every one of its
blocks is signed: the answer is then a zero to find. Every other search runs
``scipy_nelder_mead``, a cost to minimise. A written method is kept as written.

No solver runs. The choice is read off the configuration, the listing off the
CLI, and the one run goes through the closed-form ``analytic_bowl`` evaluator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibPhaseDecl, CalibrationConfig
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration, run_calibration_cli
from hydromodpy.calibration.runners.staged_runner import _phase_config, phase_summaries

pytestmark = pytest.mark.fast

STAGED = """
[calibration]
max_iter = 5

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
transform = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.001, 0.3]
target = "flow.param.Sy.field.value"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "streams.gpkg"

[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_values = [1.0, 2.0, 3.0]

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["q"]

[[calibration.phases]]
name = "k_gap"
parameters = ["K"]
objective_blocks = ["network"]

[[calibration.phases]]
name = "k_sy_gap"
parameters = ["K", "Sy"]
objective_blocks = ["network"]

[[calibration.phases]]
name = "k_nse_log"
parameters = ["K"]
objective_blocks = ["hydrograph"]

[[calibration.phases]]
name = "sy_gap"
parameters = ["Sy"]
objective_blocks = ["network"]

[[calibration.phases]]
name = "k_mixed"
parameters = ["K"]
objective_blocks = { network = 1, hydrograph = 1 }

[[calibration.phases]]
name = "k_written"
method = "grid"
parameters = ["K"]
objective_blocks = ["network"]
"""

EXPECTED = {
    "k_gap": ("bisection", "one log parameter, signed criterion"),
    "k_sy_gap": ("scipy_nelder_mead", "signed criterion on 2 parameters, cost to minimise"),
    "k_nse_log": ("scipy_nelder_mead", "cost to minimise"),
    "sy_gap": ("scipy_nelder_mead", "signed criterion, Sy not in log space, cost to minimise"),
    "k_mixed": ("scipy_nelder_mead", "cost to minimise"),
    "k_written": ("grid", None),
}


def _write(tmp_path: Path, text: str, name: str = "calibration.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def staged(tmp_path: Path) -> CalibrationConfig:
    cfg, _raw = load_toml_calibration(_write(tmp_path, STAGED))
    return cfg


@pytest.mark.parametrize("name", list(EXPECTED))
def test_each_phase_gets_the_method_its_criteria_call_for(staged, name) -> None:
    phase = next(decl for decl in staged.phases if decl.name == name)

    assert staged.method_for(phase) == EXPECTED[name]
    # The phase runs under that name: the session, the params hash and the
    # report all read it off this configuration.
    assert _phase_config(staged, phase).method == EXPECTED[name][0]


def test_the_listing_gives_the_reason_only_for_a_chosen_method(staged) -> None:
    rows = {row["name"]: row for row in phase_summaries(staged)}

    for name, (method, reason) in EXPECTED.items():
        assert rows[name]["method"] == method
        assert rows[name].get("method_reason") == reason
    assert "method_reason" not in rows["k_written"]


def test_list_phases_names_the_reason(tmp_path, capsys) -> None:
    from hydromodpy.cli.commands import calibrate as calibrate_cmd

    path = _write(tmp_path, STAGED)
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=False, list_phases=True, phase=None, profile=None)
    )

    # Each phase's own line starts with its index; a block it compares prints
    # an indented line under it, so filter those out to keep one entry per
    # phase, the way the file's own dict-based check already reads them.
    lines = [line for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")]
    assert lines[0].split("\t") == [
        "0",
        "k_gap",
        "bisection (one log parameter, signed criterion)",
        "",
        "width one mesh cell (default, measured on the mesh when the phase runs)",
    ]
    assert lines[2].split("\t")[2] == "scipy_nelder_mead (cost to minimise)"
    # k_written moves K again, which a column after the width says.
    assert lines[5].split("\t")[:4] == ["5", "k_written", "grid", ""]


def test_method_options_without_a_method_are_refused() -> None:
    with pytest.raises(ValidationError, match="method_options and no method"):
        CalibPhaseDecl.model_validate(
            {"name": "p", "parameters": ["K"], "method_options": {"sweep_points": 3}}
        )
    with pytest.raises(ValidationError, match=r"\[calibration\] gives method_options"):
        CalibrationConfig.model_validate({"method_options": {"points_per_dim": 3}})


def test_method_options_beside_a_method_are_kept() -> None:
    phase = CalibPhaseDecl.model_validate(
        {
            "name": "p",
            "method": "bisection",
            "parameters": ["K"],
            "method_options": {"sweep_points": 3},
        }
    )

    assert phase.method_options == {"sweep_points": 3}


def test_the_default_is_no_longer_grid() -> None:
    assert CalibrationConfig.model_validate({}).method is None
    assert CalibPhaseDecl.model_validate({"name": "p", "parameters": ["K"]}).method is None


SINGLE_STAGE = """
[calibration]
max_iter = 6
evaluator = "analytic_bowl"
use_cache = false

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
"""


def test_a_single_stage_calibration_with_no_method_runs_the_chosen_one(tmp_path) -> None:
    """One log parameter scored on ``objective`` (nse), which is not signed: a minimiser."""
    path = _write(tmp_path, SINGLE_STAGE)

    report = run_calibration_cli(path, workspace=tmp_path, return_report=True)

    assert report.method == "scipy_nelder_mead"
    assert report.n_iterations >= 1
    journals = list(tmp_path.rglob("session.json"))
    assert len(journals) == 1
    session = json.loads(journals[0].read_text(encoding="utf-8"))
    assert session["method"] == "scipy_nelder_mead"
    assert session["config"]["method"] == "scipy_nelder_mead"


PROJECT = """
[workspace]
project_root = "{root}"

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

BARE_K_ON_THE_GAP = """
base_config = "project.toml"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.outputs.net]
support = "network"
stream_geometry_path = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def test_python_mode_resolves_a_bare_name_and_chooses_as_the_toml_does(tmp_path) -> None:
    """A bare ``K`` is searched in the log space its field declares, from Python too.

    Left unresolved, it would search a linear space and get a minimiser where the
    same intent written in a file gets a root search.
    """
    from unittest.mock import patch

    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project import Project

    project_toml = _write(tmp_path, PROJECT.format(root=tmp_path.as_posix()), "project.toml")
    toml_cfg, _raw = load_toml_calibration(_write(tmp_path, BARE_K_ON_THE_GAP))

    class _Project:
        config = HydroModPyConfig.from_toml(project_toml)
        _config_path = project_toml
        _ctx = None

    with patch(
        "hydromodpy.calibration.runners.programmatic_runner.run_calibration_programmatic",
        return_value=None,
    ) as mocked:
        Project.calibrate(
            _Project(),
            parameters={"K": {"bounds": [1e-7, 1e-3]}},
            outputs={"net": {"support": "network", "stream_geometry_path": "streams.gpkg"}},
            objective_blocks=[
                {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        )
    python_cfg = mocked.call_args.args[0]

    assert python_cfg.parameters["K"].transform == "log"
    assert python_cfg.parameters["K"].path == toml_cfg.parameters["K"].path
    assert python_cfg.method_for() == toml_cfg.method_for()
    assert python_cfg.method_for() == ("bisection", "one log parameter, signed criterion")
