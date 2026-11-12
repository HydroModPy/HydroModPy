"""Resolution of a calibration parameter name to the config field it moves.

A file names a quantity (`K`, `bedleak`, `ru`) and the catalog finds the path of
the field, its unit and its physical range. Bounds written in another unit are
converted to the unit the field reads. Lengths are in m, conductivities in m/s
or m/day, rates in 1/s or 1/day.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
from pydantic import Field

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
)
from hydromodpy.calibration.parameter_resolution import (
    UnresolvedParameterName,
    _convert_bounds_into_the_unit_of_the_target,
    _fill_what_the_file_left_unsaid,
    _names_a_depth_model_field,
    _refuse_a_depth_model_path_the_catalogue_does_not_carry,
    _target_for,
    _why_the_depth_model_is_not_searchable,
    resolve_parameter_targets,
    unresolved_parameter_names,
)
from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.units.physical_bounds import PhysicalBoundsError, validate_physical_value
from hydromodpy.core.units.quantities import convert_to_per_s
from hydromodpy.model.domain.depth_model_config import (
    ConstantThicknessDepthModel,
    FlatSubstratumDepthModel,
    RasterSubstratumDepthModel,
    RasterThicknessDepthModel,
)
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from tests.unit.calibration._factories import _Project
from tests.unit.calibration._factories_config import sinks_project, soil_project

SECONDS_PER_DAY = 86_400.0
SOIL = "flow.sinks_sources.recharge.soil"
K_PATH = "flow.param.K.field.value"
SOIL_REPLACES_RATE = (
    "moves flow.sinks_sources.recharge.values, which the soil reservoir "
    "replaces: the search would change nothing. Calibrate ru instead, with "
    "[calibration.parameters.ru] and its bounds in mm."
)

PROJECT_TOML = textwrap.dedent(
    """
    [workspace]

    [workflow]
    mode = "simulation"

    [geographic]
    source_mode = "synthetic"

    [domain.depth_model]
    DEPTH_MODEL

    [flow.param.K.field]
    id = "K"
    kind = "homogeneous"
    unit = "m/s"
    value = 6.4e-5
    """
)


class Value(HydroModelBase):
    """A leaf that is the quantity of whatever entry carries it."""

    value: Annotated[float | None, Profile.USER] = Field(
        default=None,
        json_schema_extra=field_metadata(
            calibrable=Calibrable(
                search_space="log",
                sampling="log_uniform",
                units="m/s",
                is_the_value_of_its_instance=True,
            )
        ),
    )


class Parameter(HydroModelBase):
    field: Annotated[Value, Profile.USER] = Field(default_factory=Value)


class Lake(HydroModelBase):
    """An entry with several searchable properties and no single value."""

    bedleak: Annotated[float, Profile.USER] = Field(
        default=1e-6,
        json_schema_extra=field_metadata(calibrable=Calibrable(search_space="log", units="1/s")),
    )
    stage: Annotated[float, Profile.USER] = Field(
        default=12.0, json_schema_extra=field_metadata(calibrable=Calibrable(units="m"))
    )


class SinksSources(HydroModelBase):
    lakes: Annotated[dict[str, Lake], Profile.USER] = Field(default_factory=dict)
    recharge_value: Annotated[float | None, Profile.USER] = Field(
        default=None, json_schema_extra=field_metadata(calibrable=Calibrable(units="m/s"))
    )


class Flow(HydroModelBase):
    param: Annotated[dict[str, Parameter], Profile.USER] = Field(default_factory=dict)
    sinks_sources: Annotated[SinksSources, Profile.USER] = Field(default_factory=SinksSources)


class GeometryOnly:
    """The smallest thing the catalog walks: a domain and no flow."""

    def __init__(self, depth_model: object) -> None:
        self.domain = DomainConfig(depth_model=depth_model)


class ProjectLoadingRecharge(_Project):
    def __init__(self, flow: FlowConfig, types: list[str]) -> None:
        super().__init__(flow)
        self.data = SimpleNamespace(types=types)


def named_project(lakes: dict[str, Lake] | None = None, recharge_value: float = 3e-8) -> _Project:
    """A project with K = 1e-5 m/s, a recharge rate in m/s and some lakes."""
    return _Project(
        Flow(
            param={"K": Parameter(field=Value(value=1e-5))},
            sinks_sources=SinksSources(lakes=lakes or {}, recharge_value=recharge_value),
        )
    )


def project_reading(unit: str, value: float) -> object:
    """A project whose conductivity K is read in ``unit``."""

    class UnitValue(HydroModelBase):
        value: Annotated[float | None, Profile.USER] = Field(
            default=None,
            json_schema_extra=field_metadata(
                calibrable=Calibrable(
                    search_space="log", units=unit, is_the_value_of_its_instance=True
                )
            ),
        )

    class UnitParameter(HydroModelBase):
        field: Annotated[UnitValue, Profile.USER] = Field(default_factory=UnitValue)

    class UnitFlow(HydroModelBase):
        param: Annotated[dict[str, UnitParameter], Profile.USER] = Field(default_factory=dict)

    return SimpleNamespace(flow=UnitFlow(param={"K": UnitParameter(field=UnitValue(value=value))}))


def project_with_soil() -> _Project:
    soil = SoilReservoirConfig(ru=150.0)
    sinks_sources = FlowSinksSourcesConfig(recharge=FlowRechargeConfig(soil=soil))
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def project_without_soil() -> _Project:
    sinks_sources = FlowSinksSourcesConfig(recharge=FlowRechargeConfig())
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def lake_project(unit: str = "1/day") -> _Project:
    return sinks_project(
        lakes={"cheze": {"bedleak": 0.01, "bedleak_unit": unit, "initial_stage": 45.0}}
    )


def barrier(**values: object) -> dict[str, object]:
    return {"line": [[0.0, 0.0], [10.0, 10.0]], "depths": [5.0], **values}


def catalog(project: object) -> dict:
    return targets_by_name(calibration_targets(project))


def calibration_of(**parameters: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate({"parameters": parameters})


def resolved(project: object, **declaration: object) -> CalibrationConfig:
    """Resolve a single parameter ``K`` declared with ``declaration``."""
    calibration = calibration_of(K=declaration)
    resolve_parameter_targets(calibration, project)
    return calibration


def space_of(calibration: CalibrationConfig) -> ParameterSpace:
    return ParameterSpace.from_toml_mapping(
        {name: decl.model_dump() for name, decl in calibration.parameters.items()}
    )


def two_names_on_one_path(first_phase: list[str]) -> CalibrationConfig:
    phase = {"variable": "discharge", "objective": "nse"}
    return CalibrationConfig.model_validate(
        {
            "parameters": {
                "a": {"bounds": [1e-7, 1e-3], "path": K_PATH},
                "b": {"bounds": [1e-7, 1e-3], "path": K_PATH},
            },
            "phases": [
                {"name": "p1", "parameters": first_phase, **phase},
                {"name": "p2", "parameters": ["b"], **phase},
            ],
        }
    )


def geometry_project_file(tmp_path: Path, depth_model: str, calibration: str) -> Path:
    path = tmp_path / "project.toml"
    path.write_text(
        PROJECT_TOML.replace("DEPTH_MODEL", depth_model) + calibration, encoding="utf-8"
    )
    return path


# A field names the unit it is read in. The catalog carries that unit, not the SI
# unit of the annotation, so a sample thought in 1/s is never read in 1/day.
FIELD_UNITS = [
    pytest.param(lake_project("1/day"), "cheze.bedleak", "1/day", id="lake bed leakance"),
    pytest.param(
        sinks_project(sfr={"main": {"streambed_k": 0.5, "streambed_k_unit": "m/day"}}),
        "main.streambed_k",
        "m/day",
        id="streambed conductivity",
    ),
    pytest.param(
        sinks_project(flow_barriers={"dam": barrier(hydchr=0.1, hydchr_unit="1/day")}),
        "dam.hydchr",
        "1/day",
        id="barrier characteristic",
    ),
    pytest.param(
        sinks_project(flow_barriers={"dam": barrier(k=0.1, k_unit="m/day", thickness=1.0)}),
        "dam.k",
        "m/day",
        id="barrier conductivity",
    ),
    pytest.param(
        sinks_project(
            wells={
                "w1": {
                    "location": {"kind": "cell", "cell": [0, 1, 1]},
                    "flux": -100.0,
                    "units": "m3/day",
                }
            }
        ),
        "w1.flux",
        "m3/day",
        id="well rate",
    ),
]

# A conductivity written in m/s on a field read in m/day is converted to m/day.
# A declaration with no unit takes the unit of its field.
BOUNDS_CONVERSION = [
    pytest.param(
        "m/day",
        {"bounds": [1e-6, 1e-4], "units": "m/s"},
        "m/day",
        [1e-6 * SECONDS_PER_DAY, 1e-4 * SECONDS_PER_DAY],
        id="m/s to m/day",
    ),
    pytest.param(
        "m/s",
        {"bounds": [0.0864, 8.64], "units": "m/day"},
        "m/s",
        [1e-6, 1e-4],
        id="m/day to m/s",
    ),
    pytest.param(
        "m/day", {"bounds": [0.01, 10.0], "units": "m/day"}, "m/day", [0.01, 10.0], id="same unit"
    ),
    pytest.param("m/day", {"bounds": [0.01, 10.0]}, "m/day", [0.01, 10.0], id="no unit written"),
]

# Each row is a name, bounds in the unit of the field, the path it resolves to and
# the unit it takes. Bounds inside the physical registry resolve, the next table
# is the same names with a bound past it.
SOIL_RESOLVES = [
    pytest.param(
        "curve_number",
        [55.0, 90.0],
        soil_project(curve_number=80.0),
        f"{SOIL}.curve_number",
        "-",
        id="curve number",
    ),
    pytest.param(
        "runoff_time",
        [0.0, 5.0],
        soil_project(curve_number=80.0),
        f"{SOIL}.runoff_time",
        "day",
        id="runoff time",
    ),
    pytest.param(
        "runoff_lag",
        [0.0, 3.0],
        soil_project(curve_number=80.0),
        f"{SOIL}.runoff_lag",
        "day",
        id="runoff lag",
    ),
    pytest.param("ru", [30, 250], soil_project(), f"{SOIL}.ru", "mm", id="soil capacity"),
    pytest.param(
        "impervious_fraction",
        [0.0, 0.08],
        soil_project(),
        f"{SOIL}.impervious_fraction",
        "-",
        id="small impervious fraction",
    ),
    pytest.param(
        "impervious_fraction",
        [0.0, 0.3],
        soil_project(),
        f"{SOIL}.impervious_fraction",
        "-",
        id="large impervious fraction",
    ),
    pytest.param(
        "extinction_depth",
        [0.5, 25.0],
        sinks_project(etp=FlowEtpConfig()),
        "flow.sinks_sources.etp.extinction_depth",
        "m",
        id="EVT extinction depth",
    ),
]

SOIL_PAST_THE_REGISTRY = [
    pytest.param("curve_number", [10.0, 90.0], soil_project(curve_number=80.0), id="curve number"),
    pytest.param("runoff_time", [0.0, 20.0], soil_project(curve_number=80.0), id="runoff time"),
    pytest.param("runoff_lag", [0.0, 20.0], soil_project(curve_number=80.0), id="runoff lag"),
    pytest.param("ru", [30, 2000], soil_project(), id="soil capacity"),
    pytest.param("impervious_fraction", [0.0, 1.0], soil_project(), id="impervious fraction of 1"),
    pytest.param(
        "extinction_depth", [0.5, 500.0], sinks_project(etp=FlowEtpConfig()), id="extinction depth"
    ),
]

# A search writes a plain float into the schema, read in metres.
GEOMETRY_WRITES = [
    pytest.param(
        ConstantThicknessDepthModel(thickness="30 m"),
        "thickness",
        (5.0, 300.0),
        80.0,
        id="thickness",
    ),
    pytest.param(
        FlatSubstratumDepthModel(substratum_elevation="10 m"),
        "substratum_elevation",
        (-50.0, 50.0),
        -20.0,
        id="substratum below sea level",
    ),
]

UNIT_SPELLINGS = [
    pytest.param("Ss", 1e-7, "m-1", id="inverse metres, schema spelling"),
    pytest.param("Ss", 1e-7, "1/m", id="inverse metres, registry spelling"),
    # 8640 m/day is 0.1 m/s, inside the registry range. 1e-9 cm-1 is 1e-7 m-1.
    pytest.param("K", 8640.0, "m/day", id="conductivity per day"),
    pytest.param("Ss", 1e-9, "cm-1", id="inverse centimetres"),
]

UNRESOLVED = [
    pytest.param(
        calibration_of(porosity={"bounds": [0.01, 0.4]}, K={"bounds": [1e-7, 1e-3]}),
        named_project(),
        "porosity",
        ("'K'",),
        id="name the project lacks",
    ),
    pytest.param(
        calibration_of(thickness={"bounds": [5.0, 300.0]}),
        GeometryOnly(RasterThicknessDepthModel()),
        "thickness",
        ("raster_thickness", "exposes nothing"),
        id="thickness on a raster",
    ),
]

REFUSALS = [
    pytest.param(
        calibration_of(K={"bounds": [1e-7, 1e-3]}, K2={"bounds": [1e-7, 1e-3], "path": K_PATH}),
        named_project(recharge_value=0.0),
        ConfigError,
        r"parameters.K2\] and \[calibration.parameters.K\] both move 'flow.param.K.field.value'",
        id="name then path",
    ),
    pytest.param(
        calibration_of(
            a={"bounds": [1e-7, 1e-3], "path": K_PATH}, b={"bounds": [1e-7, 1e-3], "path": K_PATH}
        ),
        named_project(recharge_value=0.0),
        ConfigError,
        r"parameters.b\] and \[calibration.parameters.a\] both move 'flow.param.K.field.value'",
        id="path twice",
    ),
    pytest.param(
        two_names_on_one_path(["a", "b"]),
        named_project(),
        ConfigError,
        "both move",
        id="two names in one phase",
    ),
    pytest.param(
        calibration_of(
            x={"bounds": [0.5, 2.0], "mode": "scale", "path": "flow.sinks_sources.recharge_value"}
        ),
        named_project(recharge_value=0.0),
        ConfigError,
        "every factor gives the same value",
        id="scale on zero",
    ),
    pytest.param(
        calibration_of(**{"cheze.bedleak": {"bounds": [1e-3, 1e12]}}),
        lake_project("1/day"),
        ConfigError,
        "upper bound",
        id="bedleak past the range in its unit",
    ),
    pytest.param(
        calibration_of(K={"bounds": [1.0, 10.0], "units": "m"}),
        project_reading("m/day", 0.5),
        ConfigError,
        r"parameters\.K\] writes its bounds in 'm'.*'m/day'",
        id="unit of another dimension",
    ),
    pytest.param(
        calibration_of(K={"bounds": [0.5, 2.0], "units": "m/s", "mode": "scale"}),
        project_reading("m/day", 0.5),
        ConfigError,
        r"scale.*factor",
        id="unit on a scale factor",
    ),
    pytest.param(
        calibration_of(thickness={"bounds": [5.0, 300.0]}),
        GeometryOnly(RasterThicknessDepthModel()),
        UnresolvedParameterName,
        "raster_thickness",
        id="thickness on a thickness raster",
    ),
    pytest.param(
        calibration_of(thickness={"bounds": [5.0, 300.0]}),
        GeometryOnly(RasterSubstratumDepthModel()),
        UnresolvedParameterName,
        "raster_substratum",
        id="thickness on a substratum raster",
    ),
    pytest.param(
        calibration_of(h={"bounds": [5.0, 300.0], "path": "domain.depth_model.thickness"}),
        GeometryOnly(FlatSubstratumDepthModel(substratum_elevation="0 m")),
        UnresolvedParameterName,
        r"parameters\.h\] path = .*flat_substratum",
        id="thickness path on a flat substratum",
    ),
    pytest.param(
        calibration_of(**{"recharge.values": {}}),
        ProjectLoadingRecharge(project_without_soil().flow, ["recharge"]),
        ConfigError,
        r"\[data.recharge\] loads replaces",
        id="recharge loaded from data",
    ),
]


@pytest.mark.parametrize(("project", "name", "units"), FIELD_UNITS)
def test_target_unit(project, name, units) -> None:
    target = catalog(project)[name]

    assert target.units == units
    assert target.physical_bounds is not None


def test_bedleak_physical_range_follows_its_unit() -> None:
    per_day = catalog(lake_project("1/day"))["cheze.bedleak"].physical_bounds
    per_second = catalog(lake_project("1/s"))["cheze.bedleak"].physical_bounds

    assert per_day[1] == pytest.approx(per_second[1] * SECONDS_PER_DAY)


def test_barrier_conductivity_physical_range() -> None:
    project = sinks_project(flow_barriers={"dam": barrier(k=0.1, k_unit="m/day", thickness=1.0)})

    bounds = catalog(project)["dam.k"].physical_bounds

    assert bounds == pytest.approx((1e-14 * SECONDS_PER_DAY, 1e2 * SECONDS_PER_DAY))


def test_bedleak_sample_in_model_unit() -> None:
    project = lake_project("1/day")
    calibration = calibration_of(**{"cheze.bedleak": {"bounds": [1e-7, 1e-5], "units": "1/s"}})
    resolve_parameter_targets(calibration, project)
    param = space_of(calibration)["cheze.bedleak"]

    apply_parameter_to_config(project, param, param.lower)

    lake = project.flow.sinks_sources.lakes["cheze"]
    assert param.units == "1/day"
    assert convert_to_per_s(lake.bedleak, unit=lake.bedleak_unit) == pytest.approx(1e-7)


@pytest.mark.parametrize(("field_unit", "declaration", "units", "bounds"), BOUNDS_CONVERSION)
def test_bounds_converted_to_field_unit(field_unit, declaration, units, bounds) -> None:
    decl = resolved(project_reading(field_unit, 0.5), **declaration).parameters["K"]

    assert decl.units == units
    assert decl.bounds == pytest.approx(bounds)


def test_converting_twice_changes_nothing() -> None:
    project = project_reading("m/day", 0.5)
    calibration = resolved(project, bounds=[1e-6, 1e-4], units="m/s")

    resolve_parameter_targets(calibration, project)

    assert calibration.parameters["K"].bounds == pytest.approx([0.0864, 8.64])


def test_sample_in_field_unit() -> None:
    project = project_reading("m/day", 0.5)
    calibration = resolved(project, bounds=[1e-6, 1e-4], units="m/s")
    param = space_of(calibration)["K"]

    apply_parameter_to_config(project, param, param.lower)

    assert project.flow.param["K"].field.value == pytest.approx(1e-6 * SECONDS_PER_DAY)
    described = space_of(calibration).describe_values({"K": param.lower})["K"]
    assert described["units"] == "m/day"


def test_scale_factor_without_a_unit_loads() -> None:
    calibration = resolved(project_reading("m/day", 0.5), bounds=[0.5, 2.0], mode="scale")

    assert calibration.parameters["K"].bounds == [0.5, 2.0]


def test_unit_without_bounds_is_converted() -> None:
    declared = resolved(project_reading("m/day", 5.0), units="m/s").parameters["K"]

    assert (declared.units, declared.bounds) == ("m/day", None)


def test_bounds_keep_unit_without_field_unit() -> None:
    decl = calibration_of(K={"bounds": [1.0, 2.0], "units": "m/s"}).parameters["K"]

    _convert_bounds_into_the_unit_of_the_target("K", decl, SimpleNamespace(units=None))

    assert (decl.bounds, decl.units) == ([1.0, 2.0], "m/s")


@pytest.mark.parametrize(
    ("calibrable", "search_space", "bounds"),
    [
        pytest.param(None, "identity", None, id="no annotation"),
        pytest.param(
            Calibrable(bounds=(1.0, 2.0), search_space="log"), "log", [1.0, 2.0], id="annotated"
        ),
    ],
)
def test_unsaid_fields_from_annotation(calibrable, search_space, bounds) -> None:
    decl = calibration_of(K={"bounds": [3.0, 4.0]}).parameters["K"]
    decl.bounds = None

    _fill_what_the_file_left_unsaid(decl, SimpleNamespace(calibrable=calibrable, units=None))

    assert (decl.search_space, decl.bounds) == (search_space, bounds)


@pytest.mark.parametrize(("param_id", "value", "unit"), UNIT_SPELLINGS)
def test_unit_spellings_accepted(param_id, value, unit) -> None:
    assert validate_physical_value(param_id=param_id, value=value, unit=unit) == value


def test_physical_range_refuses_another_quantity() -> None:
    with pytest.raises(PhysicalBoundsError):
        validate_physical_value(param_id="K", value=1e-6, unit="m-1")


def test_out_of_range_names_both_units() -> None:
    with pytest.raises(PhysicalBoundsError) as excinfo:
        validate_physical_value(param_id="K", value=8.64e7, unit="m/day")

    assert "1000 m/s" in str(excinfo.value)


@pytest.mark.parametrize(("name", "bounds", "project", "path", "units"), SOIL_RESOLVES)
def test_soil_and_evt_parameters_resolve(name, bounds, project, path, units) -> None:
    calibration = calibration_of(**{name: {"bounds": bounds}})

    resolve_parameter_targets(calibration, project)

    assert calibration.parameters[name].path == path
    assert calibration.parameters[name].units == units


@pytest.mark.parametrize(("name", "bounds", "project"), SOIL_PAST_THE_REGISTRY)
def test_soil_bounds_past_registry_refused(name, bounds, project) -> None:
    with pytest.raises(ConfigError):
        resolve_parameter_targets(calibration_of(**{name: {"bounds": bounds}}), project)


def test_two_names_clash_in_one_phase() -> None:
    resolve_parameter_targets(two_names_on_one_path(["a"]), named_project())


def test_calibration_without_phases_is_empty() -> None:
    resolve_parameter_targets(SimpleNamespace(), named_project())
    bare = SimpleNamespace(parameters=calibration_of(K={"bounds": [1e-7, 1e-3]}).parameters)

    resolve_parameter_targets(bare, named_project())

    assert bare.parameters["K"].search_space == "log"


def test_calibration_without_parameters_resolves_nothing() -> None:
    calibration = calibration_of()

    resolve_parameter_targets(calibration, sinks_project())

    assert calibration.parameters == {}


def test_scale_on_unknown_path_silent(recwarn) -> None:
    calibration = calibration_of(
        free={"bounds": [0.5, 2.0], "mode": "scale", "path": "flow.nothing"}
    )

    resolve_parameter_targets(calibration, sinks_project())

    assert calibration.parameters["free"].path == "flow.nothing"
    assert not [item for item in recwarn if item.category is UserWarning]


def test_ambiguous_name_lists_entries() -> None:
    calibration = calibration_of(bedleak={"bounds": [1e-9, 1e-3]})

    with pytest.raises(ConfigError) as excinfo:
        resolve_parameter_targets(calibration, named_project({"cheze": Lake(), "vire": Lake()}))

    assert "cheze.bedleak" in str(excinfo.value)
    assert "vire.bedleak" in str(excinfo.value)


def test_unresolved_name_is_a_config_error() -> None:
    assert issubclass(UnresolvedParameterName, ConfigError)


@pytest.mark.parametrize(("calibration", "project", "name", "fragments"), UNRESOLVED)
def test_unresolved_parameter_names(calibration, project, name, fragments) -> None:
    refused = unresolved_parameter_names(calibration, project)

    assert set(refused) == {name}
    for fragment in fragments:
        assert fragment in refused[name]


@pytest.mark.parametrize(("model", "name", "bounds", "value"), GEOMETRY_WRITES)
def test_geometry_written_in_metres(model, name, bounds, value) -> None:
    cfg = GeometryOnly(model)
    param = CalibParameter(
        name=name, lower=bounds[0], upper=bounds[1], path=f"domain.depth_model.{name}"
    )

    apply_parameter_to_config(cfg, param, value)

    assert getattr(cfg.domain.depth_model, name) == pytest.approx(value)


def test_constant_thickness_is_listed_as_thickness() -> None:
    names = catalog(GeometryOnly(ConstantThicknessDepthModel(thickness="30 m")))

    target = names["thickness"]
    assert target.path == "domain.depth_model.thickness"
    assert target.current == pytest.approx(30.0)
    assert target.units == "m"
    assert target.physical_bounds == (0.0, 10_000.0)


def test_flat_substratum_listed_as_elevation() -> None:
    names = catalog(GeometryOnly(FlatSubstratumDepthModel(substratum_elevation="12 m")))

    target = names["substratum_elevation"]
    assert target.path == "domain.depth_model.substratum_elevation"
    assert target.current == pytest.approx(12.0)
    # The registry knows an elevation, not a substratum_elevation.
    assert target.registry_id == "elevation"
    assert target.physical_bounds == (-500.0, 9000.0)


def test_long_thickness_spelling_resolves() -> None:
    calibration = calibration_of(**{"depth_model.thickness": {"bounds": [5.0, 300.0]}})

    resolve_parameter_targets(
        calibration, GeometryOnly(ConstantThicknessDepthModel(thickness="30 m"))
    )

    assert calibration.parameters["depth_model.thickness"].path == "domain.depth_model.thickness"


def test_thickness_on_flat_substratum_refused(tmp_path: Path) -> None:
    path = geometry_project_file(
        tmp_path,
        'kind = "flat_substratum"\nsubstratum_elevation = "5 m"',
        '\n[calibration.parameters.h]\nbounds = [5.0, 300.0]\npath = "domain.depth_model.thickness"\n',
    )

    with pytest.raises(UnresolvedParameterName, match="flat_substratum"):
        HydroModPyConfig.from_toml(path)


def test_extinction_depth_unit() -> None:
    # Not the mm/day that FlowEtpConfig declares for its `values` payload.
    target = catalog(sinks_project(etp=FlowEtpConfig(extinction_depth=3.0)))["etp.extinction_depth"]

    assert target.units == "m"
    assert target.registry_id == "extinction_depth"
    assert target.physical_bounds == (1e-3, 100.0)
    assert target.current == pytest.approx(3.0)
    assert target.calibrable is not None
    assert target.calibrable.bounds is None


@pytest.mark.parametrize(
    ("name", "declaration"),
    [
        pytest.param("recharge.values", {}, id="by name"),
        pytest.param("my_rate", {"path": "flow.sinks_sources.recharge.values"}, id="by path"),
    ],
)
def test_recharge_refused_beside_soil(name, declaration) -> None:
    calibration = calibration_of(**{name: declaration})

    with pytest.raises(ConfigError) as excinfo:
        resolve_parameter_targets(calibration, project_with_soil())

    assert f"[calibration.parameters.{name}]" in str(excinfo.value)
    assert SOIL_REPLACES_RATE in str(excinfo.value)


def test_recharge_calibrable_without_soil() -> None:
    calibration = calibration_of(**{"recharge.values": {}})

    resolve_parameter_targets(calibration, project_without_soil())

    assert calibration.parameters["recharge.values"].path == "flow.sinks_sources.recharge.values"


def test_ru_calibrable_beside_soil() -> None:
    calibration = calibration_of(ru={"bounds": [30, 250]})

    resolve_parameter_targets(calibration, project_with_soil())

    assert calibration.parameters["ru"].path == f"{SOIL}.ru"


def test_recharge_calibrable_when_not_loaded() -> None:
    project = ProjectLoadingRecharge(project_without_soil().flow, ["oceanic"])
    calibration = calibration_of(**{"recharge.values": {}})

    resolve_parameter_targets(calibration, project)

    assert calibration.parameters["recharge.values"].path is not None


@pytest.mark.parametrize(
    ("name", "named"), [("K", False), ("kind", True), ("depth_model.kind", True)]
)
def test_depth_model_field_names(name: str, named: bool) -> None:
    assert _names_a_depth_model_field(name) is named


def test_depth_model_name_without_model() -> None:
    assert _why_the_depth_model_is_not_searchable(SimpleNamespace()) is None
    assert (
        _refuse_a_depth_model_path_the_catalogue_does_not_carry(
            "T", "domain.depth_model.thickness", SimpleNamespace()
        )
        is None
    )
    with pytest.raises(UnresolvedParameterName, match="names nothing this project carries"):
        _target_for("depth_model.kind", {}, [], SimpleNamespace())


@pytest.mark.parametrize(("calibration", "project", "error", "message"), REFUSALS)
def test_refusals(calibration, project, error, message) -> None:
    with pytest.raises(error, match=message):
        resolve_parameter_targets(calibration, project)
