"""A lake, stream, barrier or well value is searched in the unit its own field names.

``bedleak`` is read in ``bedleak_unit``, ``streambed_k`` in ``streambed_k_unit``,
a barrier's ``hydchr`` and ``k`` in ``hydchr_unit`` and ``k_unit``, a well's
``flux`` in ``units``. The catalogue used to give each of them the SI unit
its annotation declares, so with ``bedleak_unit = "1/day"`` a sample thought
in 1/s was read in 1/day, a factor 86 400. Each target now carries the unit
its field names and a physical range in that unit.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import ParameterSpace, apply_parameter_to_config
from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets
from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.units.leakance import convert_to_per_s
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig

pytestmark = pytest.mark.unit

SECONDS_PER_DAY = 86_400.0


class _Flow(HydroModelBase):
    sinks_sources: Annotated[FlowSinksSourcesConfig, Profile.USER] = Field(
        default_factory=FlowSinksSourcesConfig
    )


class _Project:
    def __init__(self, **sinks_sources: object) -> None:
        self.flow = _Flow(sinks_sources=FlowSinksSourcesConfig.model_validate(sinks_sources))


def _lake_project(unit: str = "1/day") -> _Project:
    return _Project(lakes={"cheze": {"bedleak": 0.01, "bedleak_unit": unit, "stageinit": 45.0}})


def _barrier(**values: object) -> dict[str, object]:
    return {"line": [[0.0, 0.0], [10.0, 10.0]], "depths": [5.0], **values}


def _targets(project: _Project) -> dict:
    return targets_by_name(calibration_targets(project))


def test_a_lake_bed_leakance_carries_the_unit_of_bedleak_unit() -> None:
    target = _targets(_lake_project())["cheze.bedleak"]

    assert target.units == "1/day"


def test_a_lake_bed_leakance_has_a_physical_range_in_that_unit() -> None:
    per_day = _targets(_lake_project("1/day"))["cheze.bedleak"].physical_bounds
    per_second = _targets(_lake_project("1/s"))["cheze.bedleak"].physical_bounds

    assert per_day is not None and per_second is not None
    assert per_day[1] == pytest.approx(per_second[1] * SECONDS_PER_DAY)


def test_a_bedleak_sample_means_what_the_model_reads() -> None:
    project = _lake_project("1/day")
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"cheze.bedleak": {"bounds": [1e-7, 1e-5], "units": "1/s"}}}
    )
    resolve_parameter_targets(calibration, project)
    space = ParameterSpace.from_toml_mapping(
        {name: decl.model_dump() for name, decl in calibration.parameters.items()}
    )
    param = space["cheze.bedleak"]

    apply_parameter_to_config(project, param, param.lower)

    lake = project.flow.sinks_sources.lakes["cheze"]
    assert param.units == "1/day"
    assert convert_to_per_s(lake.bedleak, unit=lake.bedleak_unit) == pytest.approx(1e-7)


def test_bedleak_bounds_past_the_physical_range_in_its_unit_are_refused() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"cheze.bedleak": {"bounds": [1e-3, 1e12]}}}
    )

    with pytest.raises(ConfigError, match="upper bound"):
        resolve_parameter_targets(calibration, _lake_project("1/day"))


def test_a_streambed_conductivity_carries_the_unit_of_streambed_k_unit() -> None:
    project = _Project(sfr={"main": {"streambed_k": 0.5, "streambed_k_unit": "m/day"}})
    target = _targets(project)["main.streambed_k"]

    assert target.units == "m/day"
    assert target.physical_bounds is not None


def test_a_barrier_characteristic_carries_the_unit_of_hydchr_unit() -> None:
    project = _Project(flow_barriers={"dam": _barrier(hydchr=0.1, hydchr_unit="1/day")})
    target = _targets(project)["dam.hydchr"]

    assert target.units == "1/day"
    assert target.physical_bounds is not None


def test_a_barrier_conductivity_carries_the_unit_of_k_unit() -> None:
    project = _Project(flow_barriers={"dam": _barrier(k=0.1, k_unit="m/day", thickness=1.0)})
    target = _targets(project)["dam.k"]

    assert target.units == "m/day"
    assert target.physical_bounds == pytest.approx((1e-14 * SECONDS_PER_DAY, 1e2 * SECONDS_PER_DAY))


def test_a_well_rate_carries_the_unit_of_its_units_field() -> None:
    project = _Project(
        wells={
            "w1": {
                "location": {"kind": "cell", "cell": [0, 1, 1]},
                "flux": -100.0,
                "units": "m3/day",
            }
        }
    )

    assert _targets(project)["w1.flux"].units == "m3/day"
