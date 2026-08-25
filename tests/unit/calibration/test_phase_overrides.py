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
    """They reach the configuration the prepared prefix is built from.

    Not the baseline the forks copy afterwards: a flow regime or a time step
    written after the prefix has run changes what each trial holds, but not the
    time grid the prefix already built. The transient phase then silently ran
    the single steady step of the phase before it, and its metric scored one
    sample against a constant record.
    """

    def test_the_runner_hands_them_to_the_preparation(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.calibration.optim.parameters import set_by_path

        seen: dict[str, object] = {}

        def fake_prepare(
            cfg_path, *, override_paths, parameter_space=None, steps=None, config_overrides=None
        ):
            seen["override_paths"] = dict(override_paths)
            seen["config_overrides"] = dict(config_overrides or {})
            base = SimpleNamespace(
                flow=SimpleNamespace(flow_regime="steady"),
                simulation=SimpleNamespace(time=SimpleNamespace(step_value="1 year")),
            )
            for dotted, value in (config_overrides or {}).items():
                set_by_path(base, str(dotted), value)
            return SimpleNamespace(base_cfg=base, workspace=None)

        cfg = _config([STEADY, TRANSIENT])
        ctx = fake_prepare(
            "calibration.toml",
            override_paths={"Sy": "flow.param.Sy.field.value"},
            config_overrides=dict(cfg.phases[1].overrides),
        )

        assert seen["config_overrides"]["flow.flow_regime"] == "transient"
        # The overrides must NOT appear among the paths that vary per trial:
        # those decide how much of the pipeline re-runs, and listing a time
        # step there cuts the prepared prefix down to nothing.
        assert "flow.flow_regime" not in seen["override_paths"].values()
        assert ctx.base_cfg.flow.flow_regime == "transient"
        assert ctx.base_cfg.simulation.time.step_value == "1 day"

    def test_the_two_kinds_of_path_stay_apart(self) -> None:
        from hydromodpy.calibration.runners.staged_runner import _injected_paths

        cfg = _config([STEADY, TRANSIENT])
        phase_cfg = __import__(
            "hydromodpy.calibration.runners.staged_runner", fromlist=["_phase_config"]
        )._phase_config(cfg, cfg.phases[1])

        paths = _injected_paths(phase_cfg, [])

        assert "flow.flow_regime" not in paths.values()
        assert "simulation.time.step_unit" not in paths.values()
