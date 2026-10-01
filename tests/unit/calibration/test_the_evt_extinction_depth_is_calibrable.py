"""The EVT extinction depth is offered to the calibration as ``extinction_depth``.

``flow.sinks_sources.etp.extinction_depth`` carries its own unit (``m``), which
must not be swallowed by the ``mm/day`` ``FlowEtpConfig`` declares as a sibling
for its ``values`` payload: a bound stated in metres has to reach the
physical-bounds registry in metres, not in millimetres per day.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets
from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig


class _Project:
    def __init__(self, flow: FlowConfig) -> None:
        self.flow = flow


def _project(**etp_kwargs: object) -> _Project:
    etp = FlowEtpConfig(**etp_kwargs) if etp_kwargs else FlowEtpConfig()
    sinks_sources = FlowSinksSourcesConfig(etp=etp)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def test_the_target_carries_its_own_unit_not_the_etp_values_unit() -> None:
    by_name = targets_by_name(calibration_targets(_project(extinction_depth=3.0)))

    target = by_name["etp.extinction_depth"]
    assert target.units == "m"
    assert target.registry_id == "extinction_depth"
    assert target.physical_bounds == (1e-3, 100.0)
    assert target.current == pytest.approx(3.0)
    assert target.calibrable is not None
    assert target.calibrable.bounds is None


def test_the_short_name_resolves_uniquely() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"extinction_depth": {"bounds": [0.5, 25.0]}}}
    )

    resolve_parameter_targets(calibration, _project())

    decl = calibration.parameters["extinction_depth"]
    assert decl.path == "flow.sinks_sources.etp.extinction_depth"
    assert decl.units == "m"
    assert decl.bounds == [0.5, 25.0]


def test_a_bound_outside_the_registry_is_refused_at_load() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"extinction_depth": {"bounds": [0.5, 500.0]}}}
    )

    with pytest.raises(ConfigError, match="extinction_depth"):
        resolve_parameter_targets(calibration, _project())
