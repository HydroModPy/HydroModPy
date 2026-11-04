"""Tests of `parameter_resolution`."""

from __future__ import annotations

import argparse
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
from hydromodpy.cli.commands import config as config_cmd
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.units.leakance import convert_to_per_s
from hydromodpy.core.units.physical_bounds import PhysicalBoundsError, validate_physical_value
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.spatial.domain.depth_model_config import (
    ConstantThicknessDepthModel,
    FlatSubstratumDepthModel,
    RasterSubstratumDepthModel,
    RasterThicknessDepthModel,
)
from hydromodpy.spatial.domain.domain_config import DomainConfig
from tests.unit.calibration._factories import _Project
from tests.unit.calibration._factories_config import sinks_project, soil_project

# From test_a_boundary_value_is_searched_in_the_unit_its_field_names.py
# A lake, stream, barrier or well value is searched in the unit its own field names.
#
# ``bedleak`` is read in ``bedleak_unit``, ``streambed_k`` in ``streambed_k_unit``,
# a barrier's ``hydchr`` and ``k`` in ``hydchr_unit`` and ``k_unit``, a well's
# ``flux`` in ``units``. The catalog used to give each of them the SI unit
# its annotation declares, so with ``bedleak_unit = "1/day"`` a sample thought
# in 1/s was read in 1/day, a factor 86 400. Each target now carries the unit
# its field names and a physical range in that unit.


SECONDS_PER_DAY = 86_400.0


def _lake_project(unit: str = "1/day") -> _Project:
    return sinks_project(
        lakes={"cheze": {"bedleak": 0.01, "bedleak_unit": unit, "initial_stage": 45.0}}
    )


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
    project = sinks_project(sfr={"main": {"streambed_k": 0.5, "streambed_k_unit": "m/day"}})
    target = _targets(project)["main.streambed_k"]

    assert target.units == "m/day"
    assert target.physical_bounds is not None


def test_a_barrier_characteristic_carries_the_unit_of_hydchr_unit() -> None:
    project = sinks_project(flow_barriers={"dam": _barrier(hydchr=0.1, hydchr_unit="1/day")})
    target = _targets(project)["dam.hydchr"]

    assert target.units == "1/day"
    assert target.physical_bounds is not None


def test_a_barrier_conductivity_carries_the_unit_of_k_unit() -> None:
    project = sinks_project(flow_barriers={"dam": _barrier(k=0.1, k_unit="m/day", thickness=1.0)})
    target = _targets(project)["dam.k"]

    assert target.units == "m/day"
    assert target.physical_bounds == pytest.approx((1e-14 * SECONDS_PER_DAY, 1e2 * SECONDS_PER_DAY))


def test_a_well_rate_carries_the_unit_of_its_units_field() -> None:
    project = sinks_project(
        wells={
            "w1": {
                "location": {"kind": "cell", "cell": [0, 1, 1]},
                "flux": -100.0,
                "units": "m3/day",
            }
        }
    )

    assert _targets(project)["w1.flux"].units == "m3/day"


# From test_a_parameter_names_its_quantity.py
# A calibration names a quantity, and the catalog says where it lives.
#
# ``path = "flow.param.K.field.value"`` is an address into the Pydantic tree, and
# it is the one line of a calibration that is about the schema rather than about
# the aquifer. The catalog already knows what a search can move and what holds
# it, so a file names ``K`` and the path is resolved from there.
#
# What is gated here is that the naming is derived and not declared, that a
# spelling two targets would answer to is given to neither, and that what the
# file writes always beats what the field declares.


class _Value(HydroModelBase):
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


class _Parameter(HydroModelBase):
    field: Annotated[_Value, Profile.USER] = Field(default_factory=_Value)


class _Lake(HydroModelBase):
    """An entry with several searchable properties and no single value."""

    bedleak: Annotated[float, Profile.USER] = Field(
        default=1e-6,
        json_schema_extra=field_metadata(calibrable=Calibrable(search_space="log", units="1/s")),
    )
    stage: Annotated[float, Profile.USER] = Field(
        default=12.0, json_schema_extra=field_metadata(calibrable=Calibrable(units="m"))
    )


class _SinksSources(HydroModelBase):
    lakes: Annotated[dict[str, _Lake], Profile.USER] = Field(default_factory=dict)
    recharge_value: Annotated[float | None, Profile.USER] = Field(
        default=None, json_schema_extra=field_metadata(calibrable=Calibrable(units="m/s"))
    )


class _Flow__parameter_names(HydroModelBase):
    param: Annotated[dict[str, _Parameter], Profile.USER] = Field(default_factory=dict)
    sinks_sources: Annotated[_SinksSources, Profile.USER] = Field(default_factory=_SinksSources)


def _project__parameter_names(**lakes: _Lake) -> _Project:
    return _Project(
        _Flow__parameter_names(
            param={"K": _Parameter(field=_Value(value=1e-5))},
            sinks_sources=_SinksSources(lakes=lakes, recharge_value=3e-8),
        )
    )


def _calibration(**parameters: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate({"parameters": parameters})


class TestTheNameIsDerived:
    def test_a_carrier_leaf_is_named_by_its_entry(self) -> None:
        """'K', not 'K.value': the leaf declares that it IS the value of K."""
        names = targets_by_name(calibration_targets(_project__parameter_names()))

        assert "K" in names
        assert names["K"].path == "flow.param.K.field.value"

    def test_any_other_leaf_carries_its_entry_and_its_own_name(self) -> None:
        names = targets_by_name(calibration_targets(_project__parameter_names(cheze=_Lake())))

        assert "cheze.bedleak" in names
        assert "cheze.stage" in names

    def test_a_value_no_entry_declares_is_named_by_what_holds_it(self) -> None:
        names = targets_by_name(calibration_targets(_project__parameter_names()))

        assert "sinks_sources.recharge_value" in names

    def test_a_spelling_two_targets_share_is_given_to_neither(self) -> None:
        """Two lakes both carry a bedleak, so neither answers to the short form."""
        catalogue = calibration_targets(_project__parameter_names(cheze=_Lake(), vire=_Lake()))
        names = {target.name for target in catalogue}

        assert "cheze.bedleak" in names
        assert "vire.bedleak" in names
        assert "bedleak" not in names


class TestWhatTheNameResolvesTo:
    def test_it_writes_the_path_into_the_declaration(self) -> None:
        calibration = _calibration(K={"bounds": [1e-7, 1e-3]})

        resolve_parameter_targets(calibration, _project__parameter_names())

        assert calibration.parameters["K"].path == "flow.param.K.field.value"

    def test_a_longer_spelling_resolves_when_it_is_the_only_one(self) -> None:
        calibration = _calibration(bedleak={"bounds": [1e-9, 1e-3]})

        resolve_parameter_targets(calibration, _project__parameter_names(cheze=_Lake()))

        assert calibration.parameters["bedleak"].path == "flow.sinks_sources.lakes.cheze.bedleak"

    def test_a_declared_path_wins_and_is_never_looked_up(self) -> None:
        calibration = _calibration(
            whatever={"bounds": [1.0, 2.0], "path": "flow.param.K.field.value"}
        )

        resolve_parameter_targets(calibration, _project__parameter_names())

        assert calibration.parameters["whatever"].path == "flow.param.K.field.value"

    def test_resolving_twice_changes_nothing(self) -> None:
        """Both loaders call it, so neither has to know whether the other did."""
        calibration = _calibration(K={"bounds": [1e-7, 1e-3]})
        project = _project__parameter_names()

        resolve_parameter_targets(calibration, project)
        first = calibration.parameters["K"].model_dump()
        resolve_parameter_targets(calibration, project)

        assert calibration.parameters["K"].model_dump() == first


class TestWhatItRefuses:
    def test_a_name_the_project_does_not_carry(self) -> None:
        calibration = _calibration(porosity={"bounds": [0.01, 0.4]})

        with pytest.raises(ConfigError) as excinfo:
            resolve_parameter_targets(calibration, _project__parameter_names())

        assert "porosity" in str(excinfo.value)
        assert "'K'" in str(excinfo.value)

    def test_a_name_that_contradicts_its_own_path(self) -> None:
        """The search would move one quantity and the report would name another."""
        calibration = _calibration(
            K={"bounds": [1e-9, 1e-3], "path": "flow.sinks_sources.lakes.cheze.bedleak"}
        )

        with pytest.raises(ConfigError) as excinfo:
            resolve_parameter_targets(calibration, _project__parameter_names(cheze=_Lake()))

        message = str(excinfo.value)
        assert "flow.param.K.field.value" in message
        assert "cheze.bedleak" in message

    @pytest.mark.parametrize(
        ("parameters", "message"),
        [
            (
                {
                    "K": {"bounds": [1e-7, 1e-3]},
                    "K2": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                },
                r"parameters.K2] and [calibration.parameters.K] both move 'flow.param.K.field.value'",
            ),
            (
                {
                    "a": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                    "b": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                },
                r"parameters.b] and [calibration.parameters.a] both move 'flow.param.K.field.value'",
            ),
            (
                {
                    "x": {
                        "bounds": [0.5, 2.0],
                        "mode": "scale",
                        "path": "flow.sinks_sources.recharge_value",
                    }
                },
                "every factor gives the same value",
            ),
        ],
        ids=["name-then-path", "path-twice", "scale-on-zero"],
    )
    def test_a_parameter_that_cannot_move_anything_is_refused(self, parameters, message) -> None:
        project = _project__parameter_names()
        project.flow.sinks_sources.recharge_value = 0.0

        with pytest.raises(ConfigError, match=message.replace("[", r"\[")):
            resolve_parameter_targets(_calibration(**parameters), project)

    @pytest.mark.parametrize(("first", "refused"), [(["a", "b"], True), (["a"], False)])
    def test_two_names_on_one_path_clash_only_in_a_phase_that_moves_both(
        self, first: list[str], refused: bool
    ) -> None:
        path = "flow.param.K.field.value"
        phase = {"variable": "discharge", "objective": "nse"}
        calibration = CalibrationConfig.model_validate(
            {
                "parameters": {
                    "a": {"bounds": [1e-7, 1e-3], "path": path},
                    "b": {"bounds": [1e-7, 1e-3], "path": path},
                },
                "phases": [
                    {"name": "p1", "parameters": first, **phase},
                    {"name": "p2", "parameters": ["b"], **phase},
                ],
            }
        )

        if refused:
            with pytest.raises(ConfigError, match="both move"):
                resolve_parameter_targets(calibration, _project__parameter_names())
        else:
            resolve_parameter_targets(calibration, _project__parameter_names())

    def test_a_path_outside_the_catalogue_warns_that_its_sample_is_written_as_drawn(self) -> None:
        calibration = _calibration(
            x={"bounds": [1.0, 2.0], "path": "flow.nowhere.value"}, K={"bounds": [1e-7, 1e-3]}
        )

        with pytest.warns(UserWarning, match="unit is unknown") as caught:
            resolve_parameter_targets(calibration, _project__parameter_names())

        assert caught[0].filename == __file__
        assert calibration.parameters["K"].search_space == "log"

    def test_a_calibration_without_parameters_or_phases_reads_as_empty(self) -> None:
        resolve_parameter_targets(SimpleNamespace(), _project__parameter_names())
        bare = SimpleNamespace(parameters=_calibration(K={"bounds": [1e-7, 1e-3]}).parameters)

        resolve_parameter_targets(bare, _project__parameter_names())

        assert bare.parameters["K"].search_space == "log"

    def test_a_name_the_catalogue_ignores_is_only_a_label(self) -> None:
        """A file may keep its own vocabulary, as long as it says where to write."""
        calibration = _calibration(
            K_aquifer={"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}
        )

        resolve_parameter_targets(calibration, _project__parameter_names())

        assert calibration.parameters["K_aquifer"].search_space == "log"

    def test_a_name_the_project_carries_several_times(self) -> None:
        calibration = _calibration(bedleak={"bounds": [1e-9, 1e-3]})

        with pytest.raises(ConfigError) as excinfo:
            resolve_parameter_targets(
                calibration, _project__parameter_names(cheze=_Lake(), vire=_Lake())
            )

        message = str(excinfo.value)
        assert "cheze.bedleak" in message
        assert "vire.bedleak" in message


class TestWhoWinsOverWho:
    def test_the_field_supplies_what_the_file_left_unsaid(self) -> None:
        calibration = _calibration(K={"bounds": [1e-7, 1e-3]})

        resolve_parameter_targets(calibration, _project__parameter_names())

        decl = calibration.parameters["K"]
        assert decl.search_space == "log"
        assert decl.sampling == "log_uniform"
        assert decl.units == "m/s"

    def test_a_path_written_by_hand_inherits_the_same_space(self) -> None:
        """Two spellings of one quantity must not search two different spaces."""
        named = _calibration(K={"bounds": [1e-7, 1e-3]})
        addressed = _calibration(K={"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"})
        project = _project__parameter_names()

        resolve_parameter_targets(named, project)
        resolve_parameter_targets(addressed, project)

        assert addressed.parameters["K"].model_dump() == named.parameters["K"].model_dump()

    def test_the_file_beats_the_field(self) -> None:
        """A declared 'identity' is a decision, not a default left standing.

        The unit is the exception: the sample is written in the unit the field
        reads, so bounds in another unit are converted into it
        (test_bounds_in_another_unit_are_converted_to_the_target).
        """
        calibration = _calibration(
            K={"bounds": [1e-7, 1e-3], "search_space": "identity", "units": "m/s"}
        )

        resolve_parameter_targets(calibration, _project__parameter_names())

        decl = calibration.parameters["K"]
        assert decl.search_space == "identity"
        assert decl.units == "m/s"
        assert decl.sampling == "log_uniform"


class TestTheRefusalSurvivesTheLoaders:
    """A name the project does not carry must not be forgiven by a tolerant loader.

    ``load_toml_calibration`` builds the project configuration and tolerates that
    it cannot: ``--list-phases`` has to run on a machine holding none of the data.
    That tolerance swallowed the name refusal too, and the run then failed three
    steps later on "must declare a 'path'", which accuses the form the file no
    longer has to write.
    """

    def test_it_is_typed_apart_from_a_machine_that_lacks_the_data(self) -> None:

        assert issubclass(UnresolvedParameterName, ConfigError)

    def test_an_unknown_name_raises_that_type(self) -> None:
        calibration = _calibration(porosity={"bounds": [0.01, 0.4]})

        with pytest.raises(UnresolvedParameterName):
            resolve_parameter_targets(calibration, _project__parameter_names())


class TestTheUnitTheNameBringsWithIt:
    """Naming a quantity hands its unit to the range check, which had never seen one.

    A bound used to carry a unit only when a file typed one, and almost none did.
    A parameter now inherits the unit of the field it names, so every spelling the
    schema accepts reaches the physical registry. Two of them did not survive the
    trip: the schema writes inverse meters ``m-1`` where the registry writes
    ``1/m``, and a conductivity declared in ``m/day`` was compared against a range
    written in ``m/s``.
    """

    def test_the_same_unit_spelled_the_other_way(self) -> None:
        assert validate_physical_value(param_id="Ss", value=1e-7, unit="m-1") == 1e-7
        assert validate_physical_value(param_id="Ss", value=1e-7, unit="1/m") == 1e-7

    def test_a_unit_that_needs_a_factor(self) -> None:
        # 8640 m/day is 0.1 m/s, inside the registry range; 1e-9 cm-1 is 1e-7 m-1.
        assert validate_physical_value(param_id="K", value=8640.0, unit="m/day") == 8640.0
        assert validate_physical_value(param_id="Ss", value=1e-9, unit="cm-1") == 1e-9

    def test_a_unit_of_another_quantity_is_still_refused(self) -> None:
        with pytest.raises(PhysicalBoundsError):
            validate_physical_value(param_id="K", value=1e-6, unit="m-1")

    def test_an_out_of_range_value_is_named_in_both_units(self) -> None:
        with pytest.raises(PhysicalBoundsError) as excinfo:
            validate_physical_value(param_id="K", value=8.64e7, unit="m/day")

        assert "1000 m/s" in str(excinfo.value)


class TestLoadingReportsWhereRunningRefuses:
    """The preflight exists to return every fault of a file in one pass.

    A name it cannot resolve has to be one of those faults, not the reason the
    others were never looked for. So loading a configuration leaves an
    unresolvable name alone and the preflight names it, while the loader that a
    run goes through refuses: a search that would move nothing must not start.
    """

    def test_loading_leaves_it_alone(self) -> None:
        calibration = _calibration(porosity={"bounds": [0.01, 0.4]}, K={"bounds": [1e-7, 1e-3]})

        resolve_parameter_targets(calibration, _project__parameter_names(), strict=False)

        assert calibration.parameters["porosity"].resolve_target() is None
        assert calibration.parameters["K"].resolve_target() == "flow.param.K.field.value"

    def test_and_says_why_when_asked(self) -> None:
        calibration = _calibration(porosity={"bounds": [0.01, 0.4]}, K={"bounds": [1e-7, 1e-3]})

        refused = unresolved_parameter_names(calibration, _project__parameter_names())

        assert set(refused) == {"porosity"}
        assert "'K'" in refused["porosity"]


# From test_bounds_in_another_unit_are_converted_to_the_target.py
# Bounds written in another unit than the target reads are converted when the file loads.
#
# Each sampled value is written as it is into the field, which reads it in its
# own unit. A file that writes ``units = "m/s"`` on a conductivity the project
# declares in ``m/day`` gets its bounds converted to ``m/day``, so the search
# draws in the unit the model reads and the journal says so. A unit of another
# dimension cannot be converted and is refused, naming both units. A factor of
# ``mode = "scale"`` has no unit, so writing one there is refused.


def _value_in(unit: str) -> type[HydroModelBase]:
    class _Value(HydroModelBase):
        value: Annotated[float | None, Profile.USER] = Field(
            default=None,
            json_schema_extra=field_metadata(
                calibrable=Calibrable(
                    search_space="log", units=unit, is_the_value_of_its_instance=True
                )
            ),
        )

    return _Value


def _project__bounds_another(unit: str, value: float) -> object:
    value_model = _value_in(unit)

    class _Parameter(HydroModelBase):
        field: Annotated[value_model, Profile.USER] = Field(default_factory=value_model)

    class _Flow(HydroModelBase):
        param: Annotated[dict[str, _Parameter], Profile.USER] = Field(default_factory=dict)

    class _Project:
        def __init__(self) -> None:
            self.flow = _Flow(param={"K": _Parameter(field=value_model(value=value))})

    return _Project()


def _resolved(project: object, **declaration: object) -> CalibrationConfig:
    calibration = CalibrationConfig.model_validate({"parameters": {"K": declaration}})
    resolve_parameter_targets(calibration, project)
    return calibration


def _space(calibration: CalibrationConfig) -> ParameterSpace:
    return ParameterSpace.from_toml_mapping(
        {name: decl.model_dump() for name, decl in calibration.parameters.items()}
    )


def test_bounds_in_m_per_s_on_a_conductivity_read_in_m_per_day_are_converted() -> None:
    calibration = _resolved(
        _project__bounds_another("m/day", 0.5), bounds=[1e-6, 1e-4], units="m/s"
    )

    decl = calibration.parameters["K"]
    assert decl.units == "m/day"
    assert decl.bounds == pytest.approx([1e-6 * SECONDS_PER_DAY, 1e-4 * SECONDS_PER_DAY])


def test_the_sample_is_written_in_the_unit_the_model_reads() -> None:
    project = _project__bounds_another("m/day", 0.5)
    calibration = _resolved(project, bounds=[1e-6, 1e-4], units="m/s")
    param = _space(calibration)["K"]

    apply_parameter_to_config(project, param, param.lower)

    assert project.flow.param["K"].field.value == pytest.approx(1e-6 * SECONDS_PER_DAY)
    described = _space(calibration).describe_values({"K": param.lower})["K"]
    assert described["units"] == "m/day"


def test_bounds_in_m_per_day_on_a_conductivity_read_in_m_per_s_are_converted() -> None:
    calibration = _resolved(
        _project__bounds_another("m/s", 1e-5), bounds=[0.0864, 8.64], units="m/day"
    )

    decl = calibration.parameters["K"]
    assert decl.units == "m/s"
    assert decl.bounds == pytest.approx([1e-6, 1e-4])


def test_converting_twice_changes_nothing() -> None:
    project = _project__bounds_another("m/day", 0.5)
    calibration = _resolved(project, bounds=[1e-6, 1e-4], units="m/s")

    resolve_parameter_targets(calibration, project)

    assert calibration.parameters["K"].bounds == pytest.approx([0.0864, 8.64])


def test_a_unit_of_another_dimension_is_refused_naming_both() -> None:
    with pytest.raises(ConfigError, match=r"parameters\.K\] writes its bounds in 'm'.*'m/day'"):
        _resolved(_project__bounds_another("m/day", 0.5), bounds=[1.0, 10.0], units="m")


def test_bounds_in_the_unit_the_target_reads_load_unchanged() -> None:
    calibration = _resolved(
        _project__bounds_another("m/day", 0.5), bounds=[0.01, 10.0], units="m/day"
    )

    assert calibration.parameters["K"].bounds == [0.01, 10.0]


def test_bounds_without_a_unit_take_the_one_of_the_target() -> None:
    calibration = _resolved(_project__bounds_another("m/day", 0.5), bounds=[0.01, 10.0])

    assert calibration.parameters["K"].units == "m/day"


def test_a_unit_on_a_scale_factor_is_refused() -> None:
    with pytest.raises(ConfigError, match=r"scale.*factor"):
        _resolved(
            _project__bounds_another("m/day", 0.5), bounds=[0.5, 2.0], units="m/s", mode="scale"
        )


def test_a_scale_factor_without_a_unit_loads() -> None:
    calibration = _resolved(_project__bounds_another("m/day", 0.5), bounds=[0.5, 2.0], mode="scale")

    assert calibration.parameters["K"].bounds == [0.5, 2.0]


# From test_curve_number_and_runoff_time_are_calibrable.py
# ``[calibration.parameters.curve_number]`` and ``.runoff_time`` resolve by name.
#
# Mirrors ``test_parameter_resolution.py``: the file names the
# quantity, the catalog resolves it under ``flow.sinks_sources.recharge.soil``,
# and a bound the physical registry rules out is caught at load.


def _soil(name: str, bounds: list[float], project: _Project, **extra: object):
    calibration = CalibrationConfig.model_validate(
        {"parameters": {name: {"bounds": bounds, **extra}}}
    )
    return calibration, project


SOIL = "flow.sinks_sources.recharge.soil"
RESOLVES = [
    pytest.param(
        "curve_number",
        [55.0, 90.0],
        soil_project(curve_number=80.0),
        f"{SOIL}.curve_number",
        "-",
        id="curve_number_in_dimensionless_units",
    ),
    pytest.param(
        "runoff_time",
        [0.0, 5.0],
        soil_project(curve_number=80.0),
        f"{SOIL}.runoff_time",
        "day",
        id="runoff_time_in_days",
    ),
    pytest.param(
        "runoff_lag",
        [0.0, 3.0],
        soil_project(curve_number=80.0),
        f"{SOIL}.runoff_lag",
        "day",
        id="runoff_lag_in_days",
    ),
    pytest.param(
        "ru", [30, 250], soil_project(), f"{SOIL}.ru", "mm", id="a_bound_inside_the_registry"
    ),
    pytest.param(
        "impervious_fraction",
        [0.0, 0.08],
        soil_project(),
        f"{SOIL}.impervious_fraction",
        "-",
        id="the_impervious_fraction",
    ),
    pytest.param(
        "impervious_fraction",
        [0.0, 0.3],
        soil_project(),
        f"{SOIL}.impervious_fraction",
        "-",
        id="an_impervious_fraction_inside_the_registry",
    ),
    pytest.param(
        "extinction_depth",
        [0.5, 25.0],
        sinks_project(etp=FlowEtpConfig()),
        "flow.sinks_sources.etp.extinction_depth",
        "m",
        id="the_evt_extinction_depth",
    ),
]
REFUSED = [
    pytest.param(
        "curve_number",
        [10.0, 90.0],
        soil_project(curve_number=80.0),
        id="a_curve_number_past_the_registry",
    ),
    pytest.param(
        "runoff_time",
        [0.0, 20.0],
        soil_project(curve_number=80.0),
        id="a_runoff_time_past_the_registry",
    ),
    pytest.param(
        "runoff_lag",
        [0.0, 20.0],
        soil_project(curve_number=80.0),
        id="a_runoff_lag_past_the_registry",
    ),
    pytest.param("ru", [30, 2000], soil_project(), id="a_soil_capacity_past_the_registry"),
    pytest.param(
        "impervious_fraction", [0.0, 1.0], soil_project(), id="an_impervious_fraction_of_one"
    ),
    pytest.param(
        "extinction_depth",
        [0.5, 500.0],
        sinks_project(etp=FlowEtpConfig()),
        id="an_extinction_depth_past_the_registry",
    ),
]


@pytest.mark.parametrize(("name", "bounds", "project", "path", "units"), RESOLVES)
def test_a_soil_or_etp_name_resolves_to_its_field(name, bounds, project, path, units) -> None:
    calibration, project = _soil(name, bounds, project)

    resolve_parameter_targets(calibration, project)

    decl = calibration.parameters[name]
    assert (decl.path, decl.units, decl.bounds) == (path, units, bounds)


@pytest.mark.parametrize(("name", "bounds", "project"), REFUSED)
def test_a_bound_past_the_registry_is_refused_at_load(name, bounds, project) -> None:
    calibration, project = _soil(name, bounds, project)

    with pytest.raises(ConfigError, match=name):
        resolve_parameter_targets(calibration, project)


# From test_the_aquifer_geometry_is_calibrable.py
# The aquifer geometry is a value a search may move, when it is one number.
#
# Abherve et al. (2023) fix the thickness at 30 m and call it an input, and a
# study of how the stream network depends on it has to vary it. A
# ``constant_thickness`` model holds the geometry in one thickness, and a
# ``flat_substratum`` model in one elevation: each is searchable, and the
# catalog names it the way a hydrogeologist would.
#
# A raster depth model is a map of the site. A scalar written into it would shift
# or scale the whole map, which is not what the raster answers, so it is refused
# with the kind named, rather than by the generic "names nothing" a reader cannot
# act on.


class _Config__aquifer_geometry:
    """The smallest thing the catalog walks: a domain and no flow."""

    def __init__(self, depth_model: object) -> None:
        self.domain = DomainConfig(depth_model=depth_model)


class TestTheSchemaTakesWhatASearchWrites:
    def test_a_float_written_into_the_thickness_is_read_as_metres(self) -> None:
        cfg = _Config__aquifer_geometry(ConstantThicknessDepthModel(thickness="30 m"))
        param = CalibParameter(
            name="thickness", lower=5.0, upper=300.0, path="domain.depth_model.thickness"
        )

        apply_parameter_to_config(cfg, param, 80.0)

        assert cfg.domain.depth_model.thickness == pytest.approx(80.0)

    def test_a_thickness_that_is_not_positive_is_refused_when_written(self) -> None:
        model = ConstantThicknessDepthModel(thickness="30 m")

        with pytest.raises(ValueError, match="greater than 0"):
            model.thickness = -1.0

    def test_a_substratum_elevation_may_be_written_below_sea_level(self) -> None:
        cfg = _Config__aquifer_geometry(FlatSubstratumDepthModel(substratum_elevation="10 m"))
        param = CalibParameter(
            name="substratum_elevation",
            lower=-50.0,
            upper=50.0,
            path="domain.depth_model.substratum_elevation",
        )

        apply_parameter_to_config(cfg, param, -20.0)

        assert cfg.domain.depth_model.substratum_elevation == pytest.approx(-20.0)


class TestTheCatalogueNamesTheGeometry:
    def test_a_constant_thickness_is_listed_as_thickness(self) -> None:
        names = targets_by_name(
            calibration_targets(
                _Config__aquifer_geometry(ConstantThicknessDepthModel(thickness="30 m"))
            )
        )

        target = names["thickness"]
        assert target.path == "domain.depth_model.thickness"
        assert target.current == pytest.approx(30.0)
        assert target.units == "m"
        assert target.physical_bounds == (0.0, 10_000.0)

    def test_a_flat_substratum_is_listed_as_its_elevation(self) -> None:
        names = targets_by_name(
            calibration_targets(
                _Config__aquifer_geometry(FlatSubstratumDepthModel(substratum_elevation="12 m"))
            )
        )

        target = names["substratum_elevation"]
        assert target.path == "domain.depth_model.substratum_elevation"
        assert target.current == pytest.approx(12.0)
        # The registry knows an elevation, not a substratum_elevation.
        assert target.registry_id == "elevation"
        assert target.physical_bounds == (-500.0, 9000.0)

    def test_only_the_field_of_the_declared_kind_is_listed(self) -> None:
        names = targets_by_name(
            calibration_targets(
                _Config__aquifer_geometry(FlatSubstratumDepthModel(substratum_elevation="12 m"))
            )
        )

        assert "thickness" not in names

    @pytest.mark.parametrize("model", [RasterSubstratumDepthModel(), RasterThicknessDepthModel()])
    def test_a_raster_depth_model_lists_nothing(self, model: object) -> None:
        assert calibration_targets(_Config__aquifer_geometry(model)) == []

    def test_every_geometry_target_is_one_a_parameter_may_declare(self) -> None:
        for model in (
            ConstantThicknessDepthModel(thickness="30 m"),
            FlatSubstratumDepthModel(substratum_elevation="12 m"),
        ):
            (target,) = calibration_targets(_Config__aquifer_geometry(model))
            space = ParameterSpace.from_toml_mapping(
                {"p": {"bounds": [1.0, 2.0], "path": target.path}}
            )
            assert space.parameters[0].effective_path == target.path


class TestTheNameResolves:
    def test_thickness_resolves_and_is_searched_in_log_space(self) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 300.0]})

        resolve_parameter_targets(
            calibration, _Config__aquifer_geometry(ConstantThicknessDepthModel(thickness="30 m"))
        )

        decl = calibration.parameters["thickness"]
        assert decl.path == "domain.depth_model.thickness"
        assert decl.search_space == "log"
        assert decl.sampling == "log_uniform"
        assert decl.units == "m"

    def test_the_long_spelling_resolves_to_the_same_value(self) -> None:
        calibration = _calibration(**{"depth_model.thickness": {"bounds": [5.0, 300.0]}})

        resolve_parameter_targets(
            calibration, _Config__aquifer_geometry(ConstantThicknessDepthModel(thickness="30 m"))
        )

        assert calibration.parameters["depth_model.thickness"].path == (
            "domain.depth_model.thickness"
        )

    def test_substratum_elevation_is_searched_in_linear_space(self) -> None:
        calibration = _calibration(substratum_elevation={"bounds": [-20.0, 15.0]})

        resolve_parameter_targets(
            calibration,
            _Config__aquifer_geometry(FlatSubstratumDepthModel(substratum_elevation="0 m")),
        )

        decl = calibration.parameters["substratum_elevation"]
        assert decl.path == "domain.depth_model.substratum_elevation"
        assert decl.search_space == "identity"
        assert decl.sampling == "uniform"

    def test_a_thickness_bound_past_the_registry_is_refused(self) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 20_000.0]})

        with pytest.raises(ConfigError, match=r"parameters\.thickness\] upper bound 20000"):
            resolve_parameter_targets(
                calibration,
                _Config__aquifer_geometry(ConstantThicknessDepthModel(thickness="30 m")),
            )

    def test_an_elevation_bound_past_the_registry_is_refused(self) -> None:
        calibration = _calibration(substratum_elevation={"bounds": [-900.0, 10.0]})

        with pytest.raises(
            ConfigError, match=r"parameters\.substratum_elevation\] lower bound -900"
        ):
            resolve_parameter_targets(
                calibration,
                _Config__aquifer_geometry(FlatSubstratumDepthModel(substratum_elevation="0 m")),
            )


class TestWhatIsNotSearchableIsRefusedByItsKind:
    @pytest.mark.parametrize(
        ("model", "kind"),
        [
            (RasterThicknessDepthModel(), "raster_thickness"),
            (RasterSubstratumDepthModel(), "raster_substratum"),
        ],
    )
    def test_a_thickness_named_on_a_raster_names_the_raster(self, model, kind) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 300.0]})

        with pytest.raises(UnresolvedParameterName, match=kind):
            resolve_parameter_targets(calibration, _Config__aquifer_geometry(model))

    def test_a_thickness_named_on_a_flat_substratum_names_what_it_exposes(self) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 300.0]})

        with pytest.raises(UnresolvedParameterName, match="'substratum_elevation'"):
            resolve_parameter_targets(
                calibration,
                _Config__aquifer_geometry(FlatSubstratumDepthModel(substratum_elevation="0 m")),
            )

    def test_a_raster_offset_named_by_its_path_is_refused_even_when_lenient(self) -> None:
        """A path is otherwise the way out; into the depth model it is not."""
        calibration = _calibration(
            shift={"bounds": [-5.0, 5.0], "path": "domain.depth_model.offset"}
        )

        with pytest.raises(
            UnresolvedParameterName, match=r"parameters\.shift\] path = .*raster_substratum"
        ):
            resolve_parameter_targets(
                calibration, _Config__aquifer_geometry(RasterSubstratumDepthModel()), strict=False
            )

    def test_a_thickness_path_on_a_flat_substratum_is_refused(self) -> None:
        calibration = _calibration(
            h={"bounds": [5.0, 300.0], "path": "domain.depth_model.thickness"}
        )

        with pytest.raises(
            UnresolvedParameterName, match=r"parameters\.h\] path = .*flat_substratum"
        ):
            resolve_parameter_targets(
                calibration,
                _Config__aquifer_geometry(FlatSubstratumDepthModel(substratum_elevation="0 m")),
            )

    def test_the_preflight_reads_the_same_reason(self) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 300.0]})

        refused = unresolved_parameter_names(
            calibration, _Config__aquifer_geometry(RasterThicknessDepthModel())
        )

        assert "raster_thickness" in refused["thickness"]
        assert "exposes nothing" in refused["thickness"]


_TOML = textwrap.dedent(
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


def _project__aquifer_geometry(tmp_path: Path, depth_model: str, calibration: str = "") -> Path:
    path = tmp_path / "project.toml"
    text = _TOML.replace("PROJECT_ROOT", str(tmp_path)).replace("DEPTH_MODEL", depth_model)
    path.write_text(text + calibration, encoding="utf-8")
    return path


class TestTheProjectFile:
    def test_a_thickness_named_in_the_file_is_resolved_at_load(self, tmp_path: Path) -> None:
        path = _project__aquifer_geometry(
            tmp_path,
            'kind = "constant_thickness"\nthickness = "30 m"',
            "\n[calibration.parameters.thickness]\nbounds = [5.0, 300.0]\n",
        )

        cfg = HydroModPyConfig.from_toml(path)

        decl = cfg.calibration.parameters["thickness"]
        assert decl.path == "domain.depth_model.thickness"
        assert decl.search_space == "log"

    def test_a_thickness_path_on_a_flat_substratum_stops_the_load(self, tmp_path: Path) -> None:
        path = _project__aquifer_geometry(
            tmp_path,
            'kind = "flat_substratum"\nsubstratum_elevation = "5 m"',
            '\n[calibration.parameters.h]\nbounds = [5.0, 300.0]\npath = "domain.depth_model.thickness"\n',
        )

        with pytest.raises(UnresolvedParameterName, match="flat_substratum"):
            HydroModPyConfig.from_toml(path)

    def test_config_targets_lists_the_thickness(self, tmp_path: Path, capsys) -> None:
        path = _project__aquifer_geometry(
            tmp_path, 'kind = "constant_thickness"\nthickness = "30 m"'
        )

        config_cmd.run(argparse.Namespace(config_command="targets", file=str(path), json=False))

        out = capsys.readouterr().out
        line = next(row for row in out.splitlines() if row.startswith("thickness "))
        assert "domain.depth_model.thickness" in line
        assert "30" in line

    def test_config_targets_lists_the_substratum_elevation(self, tmp_path: Path, capsys) -> None:
        path = _project__aquifer_geometry(
            tmp_path, 'kind = "flat_substratum"\nsubstratum_elevation = "5 m"'
        )

        config_cmd.run(argparse.Namespace(config_command="targets", file=str(path), json=False))

        out = capsys.readouterr().out
        assert "substratum_elevation" in out
        assert "domain.depth_model.thickness" not in out


# From test_the_evt_extinction_depth_is_calibrable.py
# The EVT extinction depth is offered to the calibration as ``extinction_depth``.
#
# ``flow.sinks_sources.etp.extinction_depth`` carries its own unit (``m``), which
# must not be swallowed by the ``mm/day`` ``FlowEtpConfig`` declares as a sibling
# for its ``values`` payload: a bound stated in meters has to reach the
# physical-bounds registry in meters, not in millimeters per day.


def test_the_target_carries_its_own_unit_not_the_etp_values_unit() -> None:
    by_name = targets_by_name(
        calibration_targets(sinks_project(etp=FlowEtpConfig(extinction_depth=3.0)))
    )

    target = by_name["etp.extinction_depth"]
    assert target.units == "m"
    assert target.registry_id == "extinction_depth"
    assert target.physical_bounds == (1e-3, 100.0)
    assert target.current == pytest.approx(3.0)
    assert target.calibrable is not None
    assert target.calibrable.bounds is None


# From test_the_physical_guard_follows_the_catalogue.py
# A zoned parameter is faced with the ceiling of the property it is a zone of.
#
# The physical registry is consulted twice on the way in, and the two consultations
# do not know the same thing. ``optim.parameters`` asks under the name the file gave
# the parameter, which is all a bare name can do. The catalog asks under the entry
# the value belongs to, read off the config tree it walked.
#
# They diverged exactly on a heterogeneous field: the catalog names a zone
# ``Sy.zone_1`` and shows the specific-yield range beside it, while
# ``PHYSICAL_BOUNDS.get("sy.zone_1")`` is None, so the guard let a zone through at
# 0.9 and refused the same 0.9 on the homogeneous form. The resolution knows the
# target, so it asks the question under the catalog's own key.


class _Zones(HydroModelBase):
    """A field whose value is one number per zone, as a heterogeneous field is."""

    values: Annotated[dict[str, float], Profile.USER] = Field(
        default_factory=dict,
        json_schema_extra=field_metadata(
            calibrable=Calibrable(search_space="log", is_the_value_of_its_instance=True)
        ),
    )


class _Parameter__physical_guard(HydroModelBase):
    field: Annotated[_Zones, Profile.USER] = Field(default_factory=_Zones)


class _Flow__physical_guard(HydroModelBase):
    param: Annotated[dict[str, _Parameter__physical_guard], Profile.USER] = Field(
        default_factory=dict
    )


def _project__physical_guard() -> _Project:
    return _Project(
        _Flow__physical_guard(
            param={"Sy": _Parameter__physical_guard(field=_Zones(values={"zone_1": 0.05}))}
        )
    )


def test_the_zone_is_named_after_the_property_it_belongs_to() -> None:
    (target,) = calibration_targets(_project__physical_guard())

    assert target.name == "Sy.zone_1"
    assert target.registry_id == "sy"
    assert target.physical_bounds == (1e-4, 0.5)


def test_a_zone_above_the_ceiling_is_refused() -> None:
    """0.9 is past the specific-yield ceiling, zoned or not."""
    calibration = _calibration(**{"Sy.zone_1": {"bounds": [1e-4, 0.9]}})

    with pytest.raises(ConfigError) as failure:
        resolve_parameter_targets(calibration, _project__physical_guard())

    assert "0.9" in str(failure.value)
    assert "specific yield" in str(failure.value)


def test_a_zone_inside_the_ceiling_is_accepted() -> None:
    calibration = _calibration(**{"Sy.zone_1": {"bounds": [1e-4, 0.3]}})

    resolve_parameter_targets(calibration, _project__physical_guard())

    assert calibration.parameters["Sy.zone_1"].path == "flow.param.Sy.field.values.zone_1"


# From test_the_replaced_recharge_rate_is_not_calibrated_in_soil_mode.py
# A search that still moves ``recharge.values`` would change nothing.
#
# The soil reservoir computes the recharge MODFLOW reads; a calibration
# parameter that reaches ``flow.sinks_sources.recharge.values``, whether by its
# own name or by an explicit path, moves a rate no builder reads once a soil
# section is declared.


_MESSAGE = (
    "moves flow.sinks_sources.recharge.values, which the soil reservoir "
    "replaces: the search would change nothing. Calibrate ru instead, with "
    "[calibration.parameters.ru] and its bounds in mm."
)


def _project_with_soil() -> _Project:
    soil = SoilReservoirConfig(ru=150.0)
    recharge = FlowRechargeConfig(soil=soil)
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def _project_without_soil() -> _Project:
    recharge = FlowRechargeConfig()
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def test_naming_the_quantity_recharge_values_is_refused() -> None:
    calibration = CalibrationConfig.model_validate({"parameters": {"recharge.values": {}}})

    with pytest.raises(ConfigError) as excinfo:
        resolve_parameter_targets(calibration, _project_with_soil())

    assert "[calibration.parameters.recharge.values]" in str(excinfo.value)
    assert _MESSAGE in str(excinfo.value)


def test_writing_the_path_to_recharge_values_is_refused() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"my_rate": {"path": "flow.sinks_sources.recharge.values"}}}
    )

    with pytest.raises(ConfigError) as excinfo:
        resolve_parameter_targets(calibration, _project_with_soil())

    assert "[calibration.parameters.my_rate]" in str(excinfo.value)
    assert _MESSAGE in str(excinfo.value)


def test_recharge_values_is_still_calibrable_without_a_soil_section() -> None:
    calibration = CalibrationConfig.model_validate({"parameters": {"recharge.values": {}}})

    resolve_parameter_targets(calibration, _project_without_soil())

    assert calibration.parameters["recharge.values"].path == "flow.sinks_sources.recharge.values"


def test_ru_is_still_calibrable_beside_a_soil_section() -> None:
    calibration = CalibrationConfig.model_validate({"parameters": {"ru": {"bounds": [30, 250]}}})

    resolve_parameter_targets(calibration, _project_with_soil())

    assert calibration.parameters["ru"].path == "flow.sinks_sources.recharge.soil.ru"


class _ProjectLoadingRecharge(_Project):
    def __init__(self, flow: FlowConfig, types: list[str]) -> None:
        super().__init__(flow)
        self.data = SimpleNamespace(types=types)


def test_a_loaded_recharge_replaces_the_rate_a_search_would_move() -> None:
    project = _ProjectLoadingRecharge(_project_without_soil().flow, ["recharge"])
    calibration = CalibrationConfig.model_validate({"parameters": {"recharge.values": {}}})

    with pytest.raises(ConfigError, match=r"\[data.recharge\] loads replaces"):
        resolve_parameter_targets(calibration, project)


def test_the_rate_stays_calibrable_when_no_recharge_is_loaded() -> None:
    project = _ProjectLoadingRecharge(_project_without_soil().flow, ["oceanic"])
    calibration = CalibrationConfig.model_validate({"parameters": {"recharge.values": {}}})

    resolve_parameter_targets(calibration, project)

    assert calibration.parameters["recharge.values"].path is not None


# -- branches that the files above do not reach ------------------------------
def test_a_calibration_without_parameters_resolves_nothing() -> None:
    calibration = _calibration()

    resolve_parameter_targets(calibration, sinks_project())

    assert calibration.parameters == {}


def test_a_scale_on_a_path_the_catalogue_does_not_carry_is_left_as_written_and_silent(
    recwarn,
) -> None:
    calibration = _calibration(free={"bounds": [0.5, 2.0], "mode": "scale", "path": "flow.nothing"})

    resolve_parameter_targets(calibration, sinks_project())

    assert calibration.parameters["free"].path == "flow.nothing"
    assert not [item for item in recwarn if item.category is UserWarning]


@pytest.mark.parametrize(
    ("name", "named"), [("K", False), ("kind", True), ("depth_model.kind", True)]
)
def test_the_depth_model_fields_are_told_from_the_other_names(name: str, named: bool) -> None:
    assert _names_a_depth_model_field(name) is named


def test_a_depth_model_name_of_a_project_without_one_falls_to_the_generic_refusal() -> None:
    assert _why_the_depth_model_is_not_searchable(SimpleNamespace()) is None
    assert (
        _refuse_a_depth_model_path_the_catalogue_does_not_carry(
            "T", "domain.depth_model.thickness", SimpleNamespace()
        )
        is None
    )
    with pytest.raises(UnresolvedParameterName, match="names nothing this project carries"):
        _target_for("depth_model.kind", {}, [], SimpleNamespace())


def test_bounds_in_a_unit_are_kept_when_the_target_reads_no_unit() -> None:
    decl = _calibration(K={"bounds": [1.0, 2.0], "units": "m/s"}).parameters["K"]

    _convert_bounds_into_the_unit_of_the_target("K", decl, SimpleNamespace(units=None))

    assert (decl.bounds, decl.units) == ([1.0, 2.0], "m/s")


def test_a_unit_without_bounds_is_converted_to_the_unit_the_target_reads() -> None:
    project = _project__bounds_another("m/day", 5.0)

    declared = _resolved(project, units="m/s").parameters["K"]

    assert (declared.units, declared.bounds) == ("m/day", None)


@pytest.mark.parametrize(
    ("calibrable", "search_space", "bounds"),
    [
        (None, "identity", None),
        (Calibrable(bounds=(1.0, 2.0), search_space="log"), "log", [1.0, 2.0]),
    ],
)
def test_what_the_file_left_unsaid_comes_from_the_annotation_when_there_is_one(
    calibrable, search_space: str, bounds
) -> None:
    decl = _calibration(K={"bounds": [3.0, 4.0]}).parameters["K"]
    decl.bounds = None

    _fill_what_the_file_left_unsaid(decl, SimpleNamespace(calibrable=calibrable, units=None))

    assert (decl.search_space, decl.bounds) == (search_space, bounds)
