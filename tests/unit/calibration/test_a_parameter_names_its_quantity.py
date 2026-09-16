"""A calibration names a quantity, and the catalogue says where it lives.

``path = "flow.param.K.field.value"`` is an address into the Pydantic tree, and
it is the one line of a calibration that is about the schema rather than about
the aquifer. The catalogue already knows what a search can move and what holds
it, so a file names ``K`` and the path is resolved from there.

What is gated here is that the naming is derived and not declared, that a
spelling two targets would answer to is given to neither, and that what the
file writes always beats what the field declares.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.parameter_resolution import (
    parameters_awaiting_resolution,
    resolve_parameter_targets,
)
from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import ConfigError


class _Value(HydroModelBase):
    """A leaf that is the quantity of whatever entry carries it."""

    value: Annotated[float | None, Profile.USER] = Field(
        default=None,
        json_schema_extra=field_metadata(
            calibrable=Calibrable(
                transform="log",
                prior="log_uniform",
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
        json_schema_extra=field_metadata(calibrable=Calibrable(transform="log", units="1/s")),
    )
    stage: Annotated[float, Profile.USER] = Field(
        default=12.0,
        json_schema_extra=field_metadata(calibrable=Calibrable(units="m")),
    )


class _SinksSources(HydroModelBase):
    lakes: Annotated[dict[str, _Lake], Profile.USER] = Field(default_factory=dict)
    recharge_value: Annotated[float | None, Profile.USER] = Field(
        default=None,
        json_schema_extra=field_metadata(calibrable=Calibrable(units="m/s")),
    )


class _Flow(HydroModelBase):
    param: Annotated[dict[str, _Parameter], Profile.USER] = Field(default_factory=dict)
    sinks_sources: Annotated[_SinksSources, Profile.USER] = Field(default_factory=_SinksSources)


class _Config:
    """The smallest thing the catalogue walks: something with a ``flow``."""

    def __init__(self, flow: _Flow) -> None:
        self.flow = flow


def _project(**lakes: _Lake) -> _Config:
    return _Config(
        _Flow(
            param={"K": _Parameter(field=_Value(value=1e-5))},
            sinks_sources=_SinksSources(lakes=lakes, recharge_value=3e-8),
        )
    )


def _calibration(**parameters: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate({"parameters": parameters})


class TestTheNameIsDerived:
    def test_a_carrier_leaf_is_named_by_its_entry(self) -> None:
        """'K', not 'K.value': the leaf declares that it IS the value of K."""
        names = targets_by_name(calibration_targets(_project()))

        assert "K" in names
        assert names["K"].path == "flow.param.K.field.value"

    def test_any_other_leaf_carries_its_entry_and_its_own_name(self) -> None:
        names = targets_by_name(calibration_targets(_project(cheze=_Lake())))

        assert "cheze.bedleak" in names
        assert "cheze.stage" in names

    def test_a_value_no_entry_declares_is_named_by_what_holds_it(self) -> None:
        names = targets_by_name(calibration_targets(_project()))

        assert "sinks_sources.recharge_value" in names

    def test_a_spelling_two_targets_share_is_given_to_neither(self) -> None:
        """Two lakes both carry a bedleak, so neither answers to the short form."""
        catalogue = calibration_targets(_project(cheze=_Lake(), vire=_Lake()))
        names = {target.name for target in catalogue}

        assert "cheze.bedleak" in names
        assert "vire.bedleak" in names
        assert "bedleak" not in names


class TestWhatTheNameResolvesTo:
    def test_it_writes_the_path_into_the_declaration(self) -> None:
        calibration = _calibration(K={"bounds": [1e-7, 1e-3]})

        resolve_parameter_targets(calibration, _project())

        assert calibration.parameters["K"].path == "flow.param.K.field.value"

    def test_a_longer_spelling_resolves_when_it_is_the_only_one(self) -> None:
        calibration = _calibration(bedleak={"bounds": [1e-9, 1e-3]})

        resolve_parameter_targets(calibration, _project(cheze=_Lake()))

        assert calibration.parameters["bedleak"].path == "flow.sinks_sources.lakes.cheze.bedleak"

    def test_a_declared_path_wins_and_is_never_looked_up(self) -> None:
        calibration = _calibration(
            whatever={"bounds": [1.0, 2.0], "path": "flow.param.K.field.value"}
        )

        resolve_parameter_targets(calibration, _project())

        assert calibration.parameters["whatever"].path == "flow.param.K.field.value"
        assert parameters_awaiting_resolution(calibration) == []

    def test_resolving_twice_changes_nothing(self) -> None:
        """Both loaders call it, so neither has to know whether the other did."""
        calibration = _calibration(K={"bounds": [1e-7, 1e-3]})
        project = _project()

        resolve_parameter_targets(calibration, project)
        first = calibration.parameters["K"].model_dump()
        resolve_parameter_targets(calibration, project)

        assert calibration.parameters["K"].model_dump() == first


class TestWhatItRefuses:
    def test_a_name_the_project_does_not_carry(self) -> None:
        calibration = _calibration(porosity={"bounds": [0.01, 0.4]})

        with pytest.raises(ConfigError) as excinfo:
            resolve_parameter_targets(calibration, _project())

        assert "porosity" in str(excinfo.value)
        assert "'K'" in str(excinfo.value)

    def test_a_name_that_contradicts_its_own_path(self) -> None:
        """The search would move one quantity and the report would name another."""
        calibration = _calibration(
            K={"bounds": [1e-9, 1e-3], "path": "flow.sinks_sources.lakes.cheze.bedleak"}
        )

        with pytest.raises(ConfigError) as excinfo:
            resolve_parameter_targets(calibration, _project(cheze=_Lake()))

        message = str(excinfo.value)
        assert "flow.param.K.field.value" in message
        assert "cheze.bedleak" in message

    def test_a_name_the_catalogue_ignores_is_only_a_label(self) -> None:
        """A file may keep its own vocabulary, as long as it says where to write."""
        calibration = _calibration(
            K_aquifer={"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}
        )

        resolve_parameter_targets(calibration, _project())

        assert calibration.parameters["K_aquifer"].transform == "log"

    def test_a_name_the_project_carries_several_times(self) -> None:
        calibration = _calibration(bedleak={"bounds": [1e-9, 1e-3]})

        with pytest.raises(ConfigError) as excinfo:
            resolve_parameter_targets(calibration, _project(cheze=_Lake(), vire=_Lake()))

        message = str(excinfo.value)
        assert "cheze.bedleak" in message
        assert "vire.bedleak" in message


class TestWhoWinsOverWho:
    def test_the_field_supplies_what_the_file_left_unsaid(self) -> None:
        calibration = _calibration(K={"bounds": [1e-7, 1e-3]})

        resolve_parameter_targets(calibration, _project())

        decl = calibration.parameters["K"]
        assert decl.transform == "log"
        assert decl.prior == "log_uniform"
        assert decl.units == "m/s"

    def test_a_path_written_by_hand_inherits_the_same_space(self) -> None:
        """Two spellings of one quantity must not search two different spaces."""
        named = _calibration(K={"bounds": [1e-7, 1e-3]})
        addressed = _calibration(K={"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"})
        project = _project()

        resolve_parameter_targets(named, project)
        resolve_parameter_targets(addressed, project)

        assert addressed.parameters["K"].model_dump() == named.parameters["K"].model_dump()

    def test_the_file_beats_the_field(self) -> None:
        """A declared 'identity' is a decision, not a default left standing."""
        calibration = _calibration(
            K={"bounds": [1e-7, 1e-3], "transform": "identity", "units": "m/day"}
        )

        resolve_parameter_targets(calibration, _project())

        decl = calibration.parameters["K"]
        assert decl.transform == "identity"
        assert decl.units == "m/day"
        assert decl.prior == "log_uniform"


class TestTheRefusalSurvivesTheLoaders:
    """A name the project does not carry must not be forgiven by a tolerant loader.

    ``load_toml_calibration`` builds the project configuration and tolerates that
    it cannot: ``--list-phases`` has to run on a machine holding none of the data.
    That tolerance swallowed the name refusal too, and the run then failed three
    steps later on "must declare a 'path'", which accuses the form the file no
    longer has to write.
    """

    def test_it_is_typed_apart_from_a_machine_that_lacks_the_data(self) -> None:
        from hydromodpy.calibration.parameter_resolution import UnresolvedParameterName
        from hydromodpy.core.exceptions import ConfigError

        assert issubclass(UnresolvedParameterName, ConfigError)

    def test_an_unknown_name_raises_that_type(self) -> None:
        from hydromodpy.calibration.parameter_resolution import UnresolvedParameterName

        calibration = _calibration(porosity={"bounds": [0.01, 0.4]})

        with pytest.raises(UnresolvedParameterName):
            resolve_parameter_targets(calibration, _project())


class TestTheUnitTheNameBringsWithIt:
    """Naming a quantity hands its unit to the range check, which had never seen one.

    A bound used to carry a unit only when a file typed one, and almost none did.
    A parameter now inherits the unit of the field it names, so every spelling the
    schema accepts reaches the physical registry. Two of them did not survive the
    trip: the schema writes inverse metres ``m-1`` where the registry writes
    ``1/m``, and a conductivity declared in ``m/day`` was compared against a range
    written in ``m/s``.
    """

    def test_the_same_unit_spelled_the_other_way(self) -> None:
        from hydromodpy.spatial.field.core.physical_bounds import validate_physical_value

        assert validate_physical_value(param_id="Ss", value=1e-7, unit="m-1") == 1e-7
        assert validate_physical_value(param_id="Ss", value=1e-7, unit="1/m") == 1e-7

    def test_a_unit_that_needs_a_factor(self) -> None:
        from hydromodpy.spatial.field.core.physical_bounds import validate_physical_value

        # 8640 m/day is 0.1 m/s, inside the registry range; 1e-9 cm-1 is 1e-7 m-1.
        assert validate_physical_value(param_id="K", value=8640.0, unit="m/day") == 8640.0
        assert validate_physical_value(param_id="Ss", value=1e-9, unit="cm-1") == 1e-9

    def test_a_unit_of_another_quantity_is_still_refused(self) -> None:
        from hydromodpy.spatial.field.core.physical_bounds import (
            PhysicalBoundsError,
            validate_physical_value,
        )

        with pytest.raises(PhysicalBoundsError):
            validate_physical_value(param_id="K", value=1e-6, unit="m-1")

    def test_an_out_of_range_value_is_named_in_both_units(self) -> None:
        from hydromodpy.spatial.field.core.physical_bounds import (
            PhysicalBoundsError,
            validate_physical_value,
        )

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

        resolve_parameter_targets(calibration, _project(), strict=False)

        assert calibration.parameters["porosity"].resolve_target() is None
        assert calibration.parameters["K"].resolve_target() == "flow.param.K.field.value"

    def test_and_says_why_when_asked(self) -> None:
        from hydromodpy.calibration.parameter_resolution import unresolved_parameter_names

        calibration = _calibration(porosity={"bounds": [0.01, 0.4]}, K={"bounds": [1e-7, 1e-3]})

        refused = unresolved_parameter_names(calibration, _project())

        assert set(refused) == {"porosity"}
        assert "'K'" in refused["porosity"]
