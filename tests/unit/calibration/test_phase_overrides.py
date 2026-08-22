"""A phase says what model it calibrates, not only how it searches.

The two stages of a stream-network calibration are one steady and one transient.
The flow regime is a property of the model, not of the search, so without this a
phase table cannot express the paper's own workflow.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig

STEADY = {
    "name": "steady_k_over_r",
    "method": "bisection",
    "parameters": ["K"],
    "freeze_on_success": True,
    "overrides": {"flow.flow_regime": "steady"},
}
TRANSIENT = {
    "name": "transient_sy",
    "method": "grid",
    "parameters": ["Sy"],
    "depends_on": "steady_k_over_r",
    "variable": "discharge",
    "objective": "nse_log",
    "overrides": {
        "flow.flow_regime": "transient",
        "simulation.time.step_value": "1 day",
    },
}


def _config(phases: list[dict]) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "parameters": {
                "K": {
                    "bounds": [1e-9, 1e-3],
                    "transform": "log",
                    "path": "flow.param.K.field.value",
                },
                "Sy": {"bounds": [1e-3, 3e-1], "path": "flow.param.Sy.field.value"},
            },
            "phases": phases,
        }
    )


class TestAccepted:
    def test_a_phase_carries_its_own_model_settings(self) -> None:
        cfg = _config([STEADY, TRANSIENT])

        assert cfg.phases[0].overrides == {"flow.flow_regime": "steady"}
        assert cfg.phases[1].overrides["simulation.time.step_value"] == "1 day"

    def test_no_override_is_the_default(self) -> None:
        cfg = _config([{"name": "p", "parameters": ["K"]}])
        assert cfg.phases[0].overrides == {}


class TestRefused:
    def test_overriding_a_path_another_phase_freezes(self) -> None:
        # The frozen value would be overwritten and nothing downstream would say
        # which of the two the model actually ran with.
        with pytest.raises(ValueError, match="freezes"):
            _config(
                [
                    STEADY,
                    {
                        **TRANSIENT,
                        "overrides": {"flow.param.K.field.value": 1e-5},
                    },
                ]
            )

    def test_rewriting_the_calibration_section(self) -> None:
        with pytest.raises(ValueError, match="own search"):
            _config([{**STEADY, "overrides": {"calibration.max_iter": 3}}])

    @pytest.mark.parametrize("path", ["", ".flow", "flow."])
    def test_a_path_that_is_not_dotted(self, path: str) -> None:
        with pytest.raises(ValueError, match="not a\n? *dotted path|dotted path"):
            _config([{**STEADY, "overrides": {path: 1}}])


class TestApplied:
    def test_the_runner_writes_them_into_the_baseline(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.calibration.runners.staged_runner import _apply_overrides

        base = SimpleNamespace(
            flow=SimpleNamespace(flow_regime="steady"),
            simulation=SimpleNamespace(time=SimpleNamespace(step_value="1 year")),
        )
        cfg = _config([STEADY, TRANSIENT])
        _apply_overrides(SimpleNamespace(base_cfg=base), cfg.phases[1])

        assert base.flow.flow_regime == "transient"
        assert base.simulation.time.step_value == "1 day"

    def test_an_unreachable_path_is_refused_by_name(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.calibration.runners.staged_runner import _apply_overrides
        from hydromodpy.core.exceptions import ConfigValidationError

        cfg = _config([{**STEADY, "overrides": {"flow.nowhere.value": 1.0}}])

        with pytest.raises(ConfigValidationError, match="cannot override"):
            _apply_overrides(
                SimpleNamespace(base_cfg=SimpleNamespace(flow=SimpleNamespace())),
                cfg.phases[0],
            )
