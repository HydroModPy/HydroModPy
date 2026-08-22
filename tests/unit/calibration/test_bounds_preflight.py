"""Pre-flight refusals the calibration runner makes before the first solve.

Two of them. A calibration bound outside what the target field accepts (e.g. a
specific yield below its physical floor) is silent until each trial that samples
there crashes at fork, so the runner probes every bound by rebuilding the flow
once. And a stream-network criterion whose drain conductance is fixed rather
than proportional to the conductivity runs to the end and returns a ratio that
means nothing, so the runner refuses it up front.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.runners.cli_runner import _assert_bounds_valid

pytestmark = pytest.mark.fast

_FLOOR = 1e-4


class _Flow:
    """Probe flow carrying the injected parameter value."""

    value: float | None = None


class _Cfg:
    """Config double exposing the ``flow`` + ``model_copy`` contract used by the probe."""

    def __init__(self) -> None:
        self.flow = _Flow()

    def model_copy(self, *, deep: bool = False) -> _Cfg:
        clone = _Cfg()
        clone.flow = _Flow()
        return clone


def _param(name, lower, upper, path="flow.param.Sy.field.value", mode="replace"):
    return SimpleNamespace(name=name, lower=lower, upper=upper, effective_path=path, mode=mode)


def _trial_ctx() -> SimpleNamespace:
    return SimpleNamespace(base_cfg=_Cfg())


@pytest.fixture()
def _floor_flow(monkeypatch):
    """Build a fake flow that rejects an injected value below the floor."""

    def fake_apply(cfg, param, value):
        cfg.flow.value = value

    def fake_flow(*, config):
        v = getattr(config, "value", None)
        if v is not None and v < _FLOOR:
            raise ValueError(f"specific yield value {v} outside [0.0001, 0.5]")
        return object()

    monkeypatch.setattr(
        "hydromodpy.calibration.optim.parameters.apply_parameter_to_config", fake_apply
    )
    monkeypatch.setattr("hydromodpy.physics.flow.Flow", fake_flow)


def test_rejects_lower_bound_below_field_floor(_floor_flow):
    space = [_param("Sy", 1e-7, 1e-1)]
    with pytest.raises(ValueError, match=r"'Sy'.*lower bound.*outside the valid range"):
        _assert_bounds_valid(_trial_ctx(), space)


def test_accepts_bounds_within_field_range(_floor_flow):
    space = [
        _param("Sy", 1e-4, 1e-1),
        _param("K", 1e-3, 1.0, path="flow.param.K.field.value"),
    ]
    _assert_bounds_valid(_trial_ctx(), space)  # no raise


def test_skips_params_without_path(_floor_flow):
    space = [_param("free", 1e-9, 1.0, path=None)]
    _assert_bounds_valid(_trial_ctx(), space)  # no raise


def test_skips_non_flow_params(_floor_flow):
    # A non-flow target is not covered by the flow rebuild probe.
    space = [_param("alpha", 1e-9, 1.0, path="transport.param.alpha")]
    _assert_bounds_valid(_trial_ctx(), space)  # no raise


def test_missing_cfg_is_noop():
    _assert_bounds_valid(SimpleNamespace(base_cfg=None), [])


class TestDrainConductanceIsProportional:
    """A network criterion needs the drain conductance to follow the conductivity.

    ``C = K * cell_area / top_thickness`` is what makes K/R the calibrated
    quantity. Both MODFLOW backends and Boussinesq apply it only when the
    configured conductance is not strictly positive, so a fixed value in
    ``[flow.bc.cauchy.drainage]`` silently costs the criterion its invariance.
    """

    @staticmethod
    def _flow(value: float | None, *, kind: str = "cauchy", active: bool = True):
        from hydromodpy.physics.flow.flow_config import FlowConfig

        payload: dict[str, object] = {"active_bc": ["drainage"] if active else []}
        if value is not None:
            payload["bc"] = {kind: {"drainage": {"value": value, "application_domain": "top"}}}
        return FlowConfig.model_validate(payload)

    @staticmethod
    def _cfg(*, network: bool = True):
        from hydromodpy.calibration.config import CalibrationConfig

        if not network:
            return CalibrationConfig.model_validate({"method": "grid", "variable": "head"})
        return CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {
                    "net": {
                        "support": "network",
                        "stream_geometry_path": "streams.gpkg",
                    }
                },
                "objective_blocks": [
                    {"name": "abherve", "metric": "distance_gap", "uses_outputs": ["net"]}
                ],
            }
        )

    def _check(self, flow, cfg) -> None:
        from hydromodpy.calibration.runners.cli_runner import (
            _assert_network_conductance_proportional,
        )

        _assert_network_conductance_proportional(
            cfg, SimpleNamespace(base_cfg=SimpleNamespace(flow=flow))
        )

    def test_a_fixed_conductance_is_refused(self) -> None:
        from hydromodpy.core.exceptions import ObjectiveError

        with pytest.raises(ObjectiveError) as excinfo:
            self._check(self._flow(1e-3), self._cfg())
        message = str(excinfo.value)
        assert "flow.bc.cauchy.drainage.value" in message
        assert "0.001" in message
        assert "'net'" in message

    def test_the_proportional_fallback_passes(self) -> None:
        self._check(self._flow(0.0), self._cfg())

    def test_a_robin_drainage_is_named_by_its_own_family(self) -> None:
        from hydromodpy.core.exceptions import ObjectiveError

        with pytest.raises(ObjectiveError, match=r"flow\.bc\.robin\.drainage\.value"):
            self._check(self._flow(2.0, kind="robin"), self._cfg())

    def test_an_active_boundary_without_a_section_passes(self) -> None:
        # Nothing declares a conductance, so nothing overrides the fallback.
        self._check(self._flow(None), self._cfg())

    def test_an_inactive_drainage_boundary_passes(self) -> None:
        self._check(self._flow(1e-3, active=False), self._cfg())

    def test_a_calibration_without_a_network_output_passes(self) -> None:
        self._check(self._flow(1e-3), self._cfg(network=False))
