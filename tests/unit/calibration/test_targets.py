"""Catalog of the quantities a calibration can search, read from a resolved configuration.

A leaf is offered only when its field carries a `Calibrable` annotation. A target
gives its dotted path, its current value, its unit (mm/day, m/s, day, ...) and the
physical range it is checked against.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated

import pytest
from pydantic import Field

from hydromodpy.calibration.targets import (
    _physical_bounds_for,
    _searched_as_written_when_signed,
    _unit_the_leaf_is_read_in,
    calibration_targets,
    targets_by_name,
    targets_by_path,
)
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.calibrable import Calibrable as reexported
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.field_param.sections import FieldHomogeneousSection
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from tests.unit.calibration._factories import _Project


def annotation_of(model: type, field: str) -> Calibrable | None:
    extra = model.model_fields[field].json_schema_extra or {}
    found = extra.get("calibrable") if isinstance(extra, dict) else None
    return found if isinstance(found, Calibrable) else None


def config_with(tmp_path, **flow: object):
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        flow=FlowConfig(**flow),
    )


@pytest.fixture
def cfg(tmp_path):
    return config_with(
        tmp_path,
        param_list=["K", "Sy"],
        param={
            "K": {"field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-5}},
            "Sy": {"field": {"id": "Sy", "kind": "homogeneous", "unit": "-", "value": 0.1}},
        },
    )


def config_with_k_written_as(tmp_path, *, value: object, unit: str | None = None):
    field: dict[str, object] = {"id": "K", "kind": "homogeneous", "value": value}
    if unit is not None:
        field["unit"] = unit
    return config_with(tmp_path, param_list=["K"], param={"K": {"field": field}})


def soil_project() -> _Project:
    soil = SoilReservoirConfig(ru=150.0)
    recharge = FlowRechargeConfig(soil=soil)
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def vertical_profile_project(**vertical_profile: object) -> _Project:
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


class _Reach(HydroModelBase):
    # A declared quantity next to an undeclared numeric sibling.
    manning: Annotated[float, Profile.USER] = Field(
        default=0.03, json_schema_extra=field_metadata(calibrable=Calibrable(units="s/m^(1/3)"))
    )
    min_slope: Annotated[float, Profile.USER] = Field(default=1e-4)


class _SinksSources(HydroModelBase):
    reaches: Annotated[dict[str, _Reach], Profile.USER] = Field(default_factory=dict)


class _Flow(HydroModelBase):
    sinks_sources: Annotated[_SinksSources, Profile.USER] = Field(default_factory=_SinksSources)


class _BarrierOptions(HydroModelBase):
    # Backend option that a declared conductivity entry settles.
    bedleak: Annotated[float, Profile.EXPERT] = Field(
        default=12.0,
        json_schema_extra=field_metadata(
            calibrable=Calibrable(
                search_space="log",
                sampling="log_uniform",
                units="1/day",
                excluded_by=("flow.param.Kv",),
            ),
            unit="-",
        ),
    )
    floor: Annotated[float, Profile.USER] = Field(default=2.0)


class _ParamInFiles(HydroModelBase):
    Kv: Annotated[float, Profile.USER] = Field(default=1e-4)


class _FlowInFiles(HydroModelBase):
    param: Annotated[dict[str, _ParamInFiles], Profile.USER] = Field(
        default_factory=lambda: {"Kv": _ParamInFiles()}
    )


def leaky_barrier_solver() -> SimpleNamespace:
    return SimpleNamespace(backend_name="leaky_barrier", options_of=lambda name: _BarrierOptions())


def test_annotation_lives_in_the_kernel() -> None:
    # Physics and spatial layers carry it without breaking the layer matrix.
    assert Calibrable.__module__ == "hydromodpy.core.config_kit.calibrable"


def test_one_calibrable_class() -> None:
    assert reexported is Calibrable


# A conductivity range belongs to the catchment, so the schema leaves bounds empty.
HOMOGENEOUS_VALUE = [
    pytest.param("search_space", "log", id="search space"),
    pytest.param("sampling", "log_uniform", id="sampling"),
    pytest.param("bounds", None, id="range left to the site"),
]


@pytest.mark.parametrize(("attribute", "expected"), HOMOGENEOUS_VALUE)
def test_homogeneous_value_annotation(attribute: str, expected: object) -> None:
    found = annotation_of(FieldHomogeneousSection, "value")

    assert getattr(found, attribute) == expected


@pytest.mark.parametrize("units", ["mm/day", "m/day"])
def test_recharge_target_unit(units: str) -> None:
    cfg = HydroModPyConfig.model_validate(
        {
            "workflow": {"mode": "simulation"},
            "workspace": {"project_root": "."},
            "site": {"name": "site_a"},
            "geographic": {
                "catchment": {
                    "kind": "from_outlet_coord",
                    "x_outlet": 1.0,
                    "y_outlet": 2.0,
                    "snap_dist": "150 m",
                    "buff_area": "20%",
                }
            },
        }
    )
    cfg.flow.sinks_sources.recharge = FlowRechargeConfig(units=units, values=1.0)

    found = {target.path: target for target in calibration_targets(cfg)}

    assert found["flow.sinks_sources.recharge.values"].units == units


def test_target_carries_the_current_value(cfg) -> None:
    target = targets_by_path(calibration_targets(cfg))["flow.param.K.field.value"]

    assert target.current == pytest.approx(1e-5)
    assert target.instance == "K"


def test_target_unit_from_sibling(cfg) -> None:
    target = targets_by_path(calibration_targets(cfg))["flow.param.K.field.value"]

    assert target.units == "m/s"


# A value in one string is the same declaration as a number with a sibling unit.
WRITTEN_K = [
    pytest.param(1e-4, "m/s", id="number with a sibling unit"),
    pytest.param("1e-4 m/s", None, id="number and unit in one string"),
]


@pytest.mark.parametrize(("value", "unit"), WRITTEN_K)
def test_k_written_two_ways(tmp_path, value: object, unit: str | None) -> None:
    cfg = config_with_k_written_as(tmp_path, value=value, unit=unit)

    found = targets_by_path(calibration_targets(cfg))

    assert found["flow.param.K.field.value"].current == pytest.approx(1e-4)


def test_string_value_fills_unit(tmp_path) -> None:
    field = config_with_k_written_as(tmp_path, value="1e-4 m/s").flow.param["K"].field

    assert field.value == pytest.approx(1e-4)
    assert field.unit == "m/s"


def test_soil_target_units() -> None:
    by_name = targets_by_name(calibration_targets(soil_project()))

    units = {
        "soil.ru": "mm",
        "soil.alpha": "-",
        "soil.kc": "-",
        "soil.impervious_fraction": "-",
        "soil.bypass_fraction": "-",
        "soil.transit_time": "day",
    }
    assert {name: by_name[name].units for name in units} == units


# A leaf under the id "K" must read its own range, not the conductivity range in m/s.
VERTICAL_PROFILE = [
    pytest.param(
        {"kind": "exponential", "characteristic_depth": 30.0},
        ("K.characteristic_depth", "characteristic_depth", "m", (0.1, 1000.0), 30.0),
        id="characteristic depth",
    ),
    pytest.param(
        {"kind": "exponential", "characteristic_depth": 30.0, "min_factor": 0.2},
        ("K.min_factor", "min_factor", "-", (1e-6, 1.0), 0.2),
        id="minimum factor",
    ),
]


@pytest.mark.parametrize(("profile", "expected"), VERTICAL_PROFILE)
def test_vertical_profile_own_range(profile: dict, expected: tuple) -> None:
    name, registry_id, units, bounds, current = expected

    by_name = targets_by_name(calibration_targets(vertical_profile_project(**profile)))

    target = by_name[name]
    assert target.registry_id == registry_id
    assert target.units == units
    assert target.physical_bounds == bounds
    assert target.current == pytest.approx(current)


def test_signed_range_search() -> None:
    plain = Calibrable(bounds=(-1.0, 1.0))
    log = Calibrable(bounds=(-1.0, 1.0), search_space="log", sampling="log_uniform")

    assert _searched_as_written_when_signed(plain, (-1.0, 1.0)) is plain
    signed = _searched_as_written_when_signed(log, (-1.0, 1.0))
    assert (signed.search_space, signed.sampling) == ("identity", "uniform")


@pytest.mark.parametrize(
    ("named", "read"),
    [
        pytest.param("1/day", "1/day", id="unit named"),
        pytest.param("  ", "1/s", id="blank name"),
        pytest.param(3, "1/s", id="not a string"),
    ],
)
def test_leaf_unit_or_default(named: object, read: str) -> None:
    declared = Calibrable(units="1/s", unit_field="bedleak_unit")

    assert _unit_the_leaf_is_read_in(SimpleNamespace(bedleak_unit=named), declared) == read


def test_unknown_unit_no_range() -> None:
    assert _physical_bounds_for("a.b", "K", "value", units="m/day") == (8.64e-10, 8640000.0)
    assert _physical_bounds_for("a.b", "K", "value", units="furlong") is None


def test_backend_option_unit() -> None:
    solver = leaky_barrier_solver()

    target = targets_by_name(calibration_targets(SimpleNamespace(solver=solver, flow=_Flow())))[
        "bedleak"
    ]

    assert (target.path, target.current, target.units) == (
        "solver.leaky_barrier.bedleak",
        12.0,
        "1/day",
    )
    assert target.calibrable is not None


def test_excluded_option_dropped() -> None:
    # The Kv a file declares settles the conductivity, so bedleak leaves.
    solver = leaky_barrier_solver()

    names = targets_by_name(
        calibration_targets(SimpleNamespace(solver=solver, flow=_FlowInFiles()))
    )

    assert "bedleak" not in names


def test_linear_reservoir_time_constant(tmp_path) -> None:
    # The backend requires time_constant, as days or as a string carrying its unit.
    cfg = config_with(tmp_path, param={}).model_copy(
        update={
            "solver": SolverConfig.model_validate(
                {"backend": "linear_reservoir", "linear_reservoir": {"time_constant": "30 days"}}
            )
        }
    )

    target = targets_by_name(calibration_targets(cfg))["time_constant"]

    assert target.path == "solver.linear_reservoir.time_constant"
    assert (target.current, target.units) == (30.0, "day")
    assert (target.calibrable.search_space, target.calibrable.sampling) == ("log", "log_uniform")


REFUSALS = [
    pytest.param("1e-4 m/s", "m/day", "conflict", id="string unit against sibling unit"),
]


@pytest.mark.parametrize(("value", "unit", "message"), REFUSALS)
def test_refusals(tmp_path, value: str, unit: str, message: str) -> None:
    with pytest.raises(Exception, match=message):
        config_with_k_written_as(tmp_path, value=value, unit=unit)
