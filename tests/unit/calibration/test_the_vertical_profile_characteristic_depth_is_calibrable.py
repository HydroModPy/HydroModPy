"""The vertical profile's characteristic_depth and min_factor are calibrable.

``flow.param.<id>.field_vertical_profile`` sits under a dict keyed by the
parameter id ("K", "Sy", ...), so ``_registry_id_for`` sees that id as the
walk's ``instance``. A param id of "K" or "Sy" is also a ``PHYSICAL_BOUNDS``
key for the conductivity or the specific yield themselves: without a leaf-first
rule for a leaf that is not its instance's headline quantity, a depth bound
declared in metres would be faced with a conductivity range in m/s and refused
on a unit mismatch that has nothing to do with the value.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets
from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.physics.flow.flow_config import FlowConfig


class _Project:
    def __init__(self, flow: FlowConfig) -> None:
        self.flow = flow


def _project(**vertical_profile: object) -> _Project:
    flow = FlowConfig.model_validate(
        {
            "flow_regime": "steady",
            "param_list": ["K", "Sy"],
            "param": {
                "K": {
                    "field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-4},
                    "field_vertical_profile": vertical_profile or None,
                },
                "Sy": {"field": {"id": "Sy", "kind": "homogeneous", "unit": "-", "value": 0.1}},
            },
        }
    )
    return _Project(flow)


def test_characteristic_depth_reads_its_own_range_not_k() -> None:
    by_name = targets_by_name(
        calibration_targets(_project(mode="exponential", characteristic_depth=30.0))
    )

    target = by_name["K.characteristic_depth"]
    assert target.registry_id == "characteristic_depth"
    assert target.registry_id != "k"
    assert target.units == "m"
    assert target.physical_bounds == (0.1, 1000.0)
    assert target.current == pytest.approx(30.0)


def test_min_factor_reads_its_own_range_not_k() -> None:
    by_name = targets_by_name(
        calibration_targets(_project(mode="exponential", characteristic_depth=30.0, min_factor=0.2))
    )

    target = by_name["K.min_factor"]
    assert target.registry_id == "min_factor"
    assert target.units == "-"
    assert target.physical_bounds == (1e-6, 1.0)
    assert target.current == pytest.approx(0.2)


def test_the_short_name_resolves_uniquely_and_reaches_the_field() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"K.characteristic_depth": {"bounds": [5.0, 200.0]}}}
    )

    resolve_parameter_targets(calibration, _project(mode="exponential", characteristic_depth=30.0))

    decl = calibration.parameters["K.characteristic_depth"]
    assert decl.path == "flow.param.K.field_vertical_profile.characteristic_depth"
    assert decl.units == "m"


def test_a_bound_past_the_ceiling_is_refused_not_faced_with_k() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"K.characteristic_depth": {"bounds": [5.0, 5000.0]}}}
    )

    with pytest.raises(ConfigError, match="characteristic depth"):
        resolve_parameter_targets(
            calibration, _project(mode="exponential", characteristic_depth=30.0)
        )
