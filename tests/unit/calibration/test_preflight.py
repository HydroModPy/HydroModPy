"""Everything a calibration needs, checked before the first solve.

A calibration is hours of solver time. Until now every check fired where it sat:
a missing stream geometry when the criterion first ran, a typo in a parameter
path at the first trial, a phase that cannot describe a runnable calibration
when its turn came, after the phases before it had spent their whole budget.
Each one cost the run that had already happened.

Preflight runs the static checks together, before anything solves, and reports
every problem rather than the first: a file with three mistakes takes one pass
to fix instead of three overnight runs.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.calibration.preflight import PreflightFinding, preflight_calibration
from hydromodpy.config import HydroModPyConfig

_BASE = """
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

[flow.param.Sy.field]
id = "Sy"
kind = "homogeneous"
unit = "-"
value = 0.05
"""

_GOOD = """
[calibration]
method = "grid"
max_iter = 4

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"
"""


def _write(tmp_path: Path, calibration: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text((_BASE + calibration).replace("PROJECT_ROOT", str(tmp_path)), encoding="utf-8")
    return path


def _preflight(path: Path):
    """Load the way the CLI does, then check; loading lives a layer above."""
    try:
        cfg = HydroModPyConfig.from_toml(path)
    except Exception as exc:
        return [PreflightFinding("error", path.name, f"the file does not load: {exc}")]
    return preflight_calibration(cfg, source=path)


def _messages(findings) -> str:
    return " | ".join(f"{item.where}: {item.detail}" for item in findings)


class TestAFileThatIsFine:
    def test_it_reports_nothing(self, tmp_path) -> None:
        assert _preflight(_write(tmp_path, _GOOD)) == []


class TestParameters:
    def test_a_path_the_configuration_does_not_carry_is_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.Kh]
                bounds = [1e-7, 1e-3]
                path = "flow.param.Kh.field.value"
                """,
            )
        )

        assert "flow.param.Kh.field.value" in _messages(findings)

    def test_bounds_the_wrong_way_round_are_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.K]
                bounds = [1e-3, 1e-7]
                path = "flow.param.K.field.value"
                """,
            )
        )

        assert findings
        assert "bounds" in _messages(findings)

    def test_a_bound_outside_the_physical_range_is_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.Sy]
                bounds = [1e-4, 0.8]
                path = "flow.param.Sy.field.value"
                units = "-"
                """,
            )
        )

        assert findings
        assert "Sy" in _messages(findings)


class TestOutputs:
    def test_a_stream_geometry_that_is_not_there_is_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.K]
                bounds = [1e-7, 1e-3]
                path = "flow.param.K.field.value"

                [calibration.outputs.net]
                support = "network"
                stream_geometry_path = "nowhere.gpkg"

                [[calibration.objective_blocks]]
                name = "gap"
                metric = "distance_gap"
                uses_outputs = ["net"]
                """,
            )
        )

        assert "nowhere.gpkg" in _messages(findings)

    def test_an_observed_network_source_the_project_does_not_carry_is_named(self, tmp_path) -> None:
        """Paired with an unrelated fault: neither may crowd out the other."""
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.K]
                bounds = [1e-3, 1e-7]
                path = "flow.param.K.field.value"

                [calibration.outputs.net]
                support = "network"
                observed_network = "geographic.river_network"

                [[calibration.objective_blocks]]
                name = "gap"
                metric = "distance_gap"
                uses_outputs = ["net"]
                """,
            )
        )

        messages = _messages(findings)
        assert "geographic.river_network" in messages
        assert "bounds" in messages

    def test_a_block_using_an_output_nobody_declared_is_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.K]
                bounds = [1e-7, 1e-3]
                path = "flow.param.K.field.value"

                [[calibration.objective_blocks]]
                name = "gap"
                metric = "rmse"
                uses_outputs = ["ghost"]
                """,
            )
        )

        assert "ghost" in _messages(findings)


class TestPhases:
    _PHASES = """
    [calibration]
    method = "grid"

    [calibration.parameters.K]
    bounds = [1e-7, 1e-3]
    path = "flow.param.K.field.value"

    [calibration.parameters.Sy]
    bounds = [1e-3, 0.35]
    path = "flow.param.Sy.field.value"
    units = "-"

    [[calibration.phases]]
    name = "one"
    method = "grid"
    parameters = ["{first}"]

    [[calibration.phases]]
    name = "two"
    method = "grid"
    parameters = ["Sy"]
    depends_on = "{depends}"
    """

    def test_a_phase_moving_a_parameter_nobody_declared_is_named(self, tmp_path) -> None:
        findings = _preflight(_write(tmp_path, self._PHASES.format(first="ghost", depends="one")))

        assert "ghost" in _messages(findings)

    def test_a_dependency_that_does_not_exist_is_named(self, tmp_path) -> None:
        findings = _preflight(_write(tmp_path, self._PHASES.format(first="K", depends="nowhere")))

        assert "nowhere" in _messages(findings)


class TestItReportsEverythingAtOnce:
    def test_three_mistakes_come_back_together(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.Kh]
                bounds = [1e-3, 1e-7]
                path = "flow.param.Kh.field.value"

                [[calibration.objective_blocks]]
                name = "gap"
                metric = "rmse"
                uses_outputs = ["ghost"]
                """,
            )
        )

        assert len(findings) >= 3


class TestAFileThatWillNotLoad:
    def test_it_says_so_once_rather_than_guessing(self, tmp_path) -> None:
        path = tmp_path / "broken.toml"
        path.write_text("[calibration]\nnot_a_key = 1\n", encoding="utf-8")

        findings = _preflight(path)

        assert len(findings) == 1
        assert findings[0].severity == "error"

    def test_a_file_without_a_calibration_section_says_so(self, tmp_path) -> None:
        path = tmp_path / "plain.toml"
        path.write_text(_BASE.replace("PROJECT_ROOT", str(tmp_path)), encoding="utf-8")

        findings = _preflight(path)

        assert "calibration" in _messages(findings)


class TestALinearizedWidth:
    """A width is built after the last solve, so what forbids it is checked first."""

    _LINEARIZED = """
[calibration]
method = "grid"
max_iter = 4
warmup_periods = WARMUP

[calibration.uncertainty]
method = "linearized"
perturbation = 0.01

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.outputs.gauge]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observes = "NANCON"
"""

    def _findings(self, tmp_path, warmup: int):
        return _preflight(_write(tmp_path, self._LINEARIZED.replace("WARMUP", str(warmup))))

    def test_a_burn_in_is_refused_before_the_first_solve(self, tmp_path) -> None:
        findings = self._findings(tmp_path, 6)

        assert any(item.severity == "error" for item in findings)
        assert "warmup_periods drops the first 6" in _messages(findings)

    def test_without_one_the_width_is_not_refused(self, tmp_path) -> None:
        assert "warmup_periods drops" not in _messages(self._findings(tmp_path, 0))
