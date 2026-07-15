"""Pre-flight validation of calibration parameter bounds.

A calibration bound outside what the target field accepts (e.g. a specific
yield below its physical floor) is silent until each trial that samples there
crashes at fork. Field validation only fires when the flow is built, so the
runner probes every bound by rebuilding the flow once and rejects out-of-range
bounds up front, with a clear message, instead of losing trials.
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
