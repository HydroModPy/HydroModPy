"""An engine says what it can be handed, before the search is built.

A bisection refuses a two-parameter space, refuses a parameter that is not
searched in log10, and reads a signed residual the criterion has to publish. All
three refusals live in its constructor, which is right and late: a staged
calibration builds phase two's optimizer when phase two starts, after phase one
has spent its whole solve budget on a run that was never going to finish.

The engine now declares the same three facts, and preflight reads them.
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


def _check(tmp_path: Path, calibration: str) -> list[PreflightFinding]:
    path = tmp_path / "calib.toml"
    path.write_text(
        (_BASE + textwrap.dedent(calibration)).replace("PROJECT_ROOT", str(tmp_path)),
        encoding="utf-8",
    )
    return preflight_calibration(HydroModPyConfig.from_toml(path), source=path)


def _messages(findings: list[PreflightFinding]) -> str:
    return " | ".join(f"{item.where}: {item.detail}" for item in findings)


_TWO_LOG_PARAMS = """
[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [1e-3, 0.35]
transform = "log"
path = "flow.param.Sy.field.value"
units = "-"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "PROJECT_ROOT/net.gpkg"

[[calibration.objective_blocks]]
name = "gap"
metric = "distance_gap"
uses_outputs = ["net"]
"""


class TestWhatTheEngineDeclares:
    def test_the_bisection_declares_its_three_limits(self) -> None:
        from hydromodpy.calibration.optim.optimizer import engine_traits

        traits = engine_traits("bisection")

        assert traits.max_parameters == 1
        assert traits.required_transform == "log"
        assert traits.needs_signed_residual is True

    def test_an_engine_that_constrains_nothing_declares_nothing(self) -> None:
        from hydromodpy.calibration.optim.optimizer import engine_traits

        traits = engine_traits("grid")

        assert traits.max_parameters is None
        assert traits.required_transform is None
        assert traits.needs_signed_residual is False


class TestWhatPreflightCatches:
    def test_a_root_search_over_two_parameters_is_refused(self, tmp_path) -> None:
        (tmp_path / "net.gpkg").write_bytes(b"")
        findings = _check(
            tmp_path,
            '[calibration]\nmethod = "bisection"\n' + _TWO_LOG_PARAMS,
        )

        assert "bisection" in _messages(findings)
        assert "K, Sy" in _messages(findings)

    def test_a_root_search_on_a_metric_with_no_residual_is_refused(self, tmp_path) -> None:
        findings = _check(
            tmp_path,
            """
            [calibration]
            method = "bisection"
            variable = "discharge"
            objective = "nse_log"

            [calibration.parameters.K]
            bounds = [1e-7, 1e-3]
            transform = "log"
            path = "flow.param.K.field.value"
            """,
        )

        assert "signed residual" in _messages(findings)
        assert "nse_log" in _messages(findings)

    def test_a_root_search_on_a_linear_parameter_is_refused(self, tmp_path) -> None:
        (tmp_path / "net.gpkg").write_bytes(b"")
        findings = _check(
            tmp_path,
            """
            [calibration]
            method = "bisection"

            [calibration.parameters.K]
            bounds = [1e-7, 1e-3]
            path = "flow.param.K.field.value"

            [calibration.outputs.net]
            support = "network"
            stream_geometry_path = "PROJECT_ROOT/net.gpkg"

            [[calibration.objective_blocks]]
            name = "gap"
            metric = "distance_gap"
            uses_outputs = ["net"]
            """,
        )

        assert "transform" in _messages(findings)

    def test_a_method_nobody_registered_is_refused(self, tmp_path) -> None:
        findings = _check(
            tmp_path,
            """
            [calibration]
            method = "gradient_descent_by_hand"

            [calibration.parameters.K]
            bounds = [1e-7, 1e-3]
            path = "flow.param.K.field.value"
            """,
        )

        assert "not registered" in _messages(findings)

    def test_asking_a_serial_engine_for_workers_is_only_a_warning(self, tmp_path) -> None:
        (tmp_path / "net.gpkg").write_bytes(b"")
        findings = _check(
            tmp_path,
            """
            [calibration]
            method = "bisection"
            parallel = 4
            batch_size = 4

            [calibration.parameters.K]
            bounds = [1e-7, 1e-3]
            transform = "log"
            path = "flow.param.K.field.value"

            [calibration.outputs.net]
            support = "network"
            stream_geometry_path = "PROJECT_ROOT/net.gpkg"

            [[calibration.objective_blocks]]
            name = "gap"
            metric = "distance_gap"
            uses_outputs = ["net"]
            """,
        )

        assert [finding.severity for finding in findings] == ["warning"]

    def test_a_sound_root_search_passes(self, tmp_path) -> None:
        (tmp_path / "net.gpkg").write_bytes(b"")
        findings = _check(
            tmp_path,
            """
            [calibration]
            method = "bisection"

            [calibration.parameters.K]
            bounds = [1e-7, 1e-3]
            transform = "log"
            path = "flow.param.K.field.value"

            [calibration.outputs.net]
            support = "network"
            stream_geometry_path = "PROJECT_ROOT/net.gpkg"

            [[calibration.objective_blocks]]
            name = "gap"
            metric = "distance_gap"
            uses_outputs = ["net"]
            """,
        )

        assert findings == []


def test_a_root_search_on_the_mean_distance_is_refused(tmp_path) -> None:
    """The bracket closes on a zero the mean's minimum does not sit on."""
    (tmp_path / "net.gpkg").write_bytes(b"")
    findings = _check(
        tmp_path,
        """
        [calibration]
        method = "bisection"

        [calibration.parameters.K]
        bounds = [1e-7, 1e-3]
        transform = "log"
        path = "flow.param.K.field.value"

        [calibration.outputs.net]
        support = "network"
        stream_geometry_path = "PROJECT_ROOT/net.gpkg"

        [[calibration.objective_blocks]]
        name = "mean"
        metric = "distance_mean"
        uses_outputs = ["net"]
        """,
    )

    message = _messages(findings)
    assert "distance_mean" in message
    assert "distance_gap" in message
