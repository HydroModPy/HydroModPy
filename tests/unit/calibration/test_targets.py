"""Tests of `targets`."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field

from hydromodpy.calibration import Calibrable as reexported
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets
from hydromodpy.calibration.targets import (
    VKA_PATH,
    calibration_targets,
    declared_calibrable,
    targets_by_name,
    targets_by_path,
)
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.spatial.field.field_param_sections import FieldHomogeneousSection
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests.unit.calibration._factories import _Project
from tests.unit.calibration._factories_config import sinks_project

# From test_a_field_declares_itself_calibrable.py
# The annotation had no reachable field to sit on, so it annotated nothing.
#
# ``Calibrable`` and the walk that collects it were written, tested, and returned an
# empty dictionary on every configuration in the repository. The reason was a layer
# rule, not an oversight: the annotation lived in ``calibration/``, which ``physics``
# and ``spatial`` are forbidden to import, so no hydraulic property could carry it.
#
# Moved into the kernel, any layer that declares a field can say what a search
# would need to know about it. The scalar value of a homogeneous field parameter is
# the first and most obvious one: it is the target every calibration in the
# repository writes to.


def _annotation(model: type, field: str) -> Calibrable | None:
    extra = model.model_fields[field].json_schema_extra or {}
    found = extra.get("calibrable") if isinstance(extra, dict) else None
    return found if isinstance(found, Calibrable) else None


class TestTheAnnotationIsReachable:
    def test_it_lives_in_the_kernel(self) -> None:
        """So physics and spatial can carry it without breaking the layer matrix."""
        assert Calibrable.__module__ == "hydromodpy.core.config_kit.calibrable"

    def test_there_is_one_class_and_not_two(self) -> None:
        assert reexported is Calibrable


class TestWhatIsAnnotated:
    def test_a_homogeneous_field_value_declares_itself(self) -> None:
        found = _annotation(FieldHomogeneousSection, "value")

        assert found is not None

    def test_it_declares_the_space_to_search_in(self) -> None:
        found = _annotation(FieldHomogeneousSection, "value")

        assert found is not None
        assert found.search_space == "log"
        assert found.sampling == "log_uniform"

    def test_it_leaves_the_range_to_the_site(self) -> None:
        """A conductivity range is a property of the catchment, not of the schema."""
        found = _annotation(FieldHomogeneousSection, "value")

        assert found is not None
        assert found.bounds is None

    def test_the_catalogue_reads_it_off_the_field(self) -> None:
        """The walk that builds the catalog is the one that collects it."""
        found = declared_calibrable(FieldHomogeneousSection.model_fields["value"])

        assert isinstance(found, Calibrable)

    def test_it_declares_itself_the_value_of_its_parameter(self) -> None:
        """Which is what lets a file write 'K' instead of 'K.value'."""
        found = declared_calibrable(FieldHomogeneousSection.model_fields["value"])

        assert found is not None
        assert found.is_the_value_of_its_instance


# From test_recharge_target_units.py
# The recharge rate a search moves is read in the unit the file declares.


@pytest.mark.parametrize("units", ["mm/day", "m/day"])
def test_recharge_target_reads_the_unit_of_the_recharge_block(units: str) -> None:
    cfg = HydroModPyConfig.model_validate(
        {
            "workflow": {"mode": "simulation"},
            "workspace": {"project_root": "."},
            "site": {"name": "site_a"},
            "geographic": {"catchment": {"kind": "dem", "dem_init_path": "dem.tif"}},
        }
    )
    cfg.flow.sinks_sources.recharge = FlowRechargeConfig(units=units, values=1.0)

    found = {target.path: target for target in calibration_targets(cfg)}

    assert found["flow.sinks_sources.recharge.values"].units == units


# From test_the_catalogue_is_declared_not_guessed.py
# The catalog reads a declaration, it does not guess from a name and a type.
#
# A leaf used to be offered when it was a real number, showed to Profile.USER, and
# its name was absent from a hand-written blocklist. That blocklist could go stale
# without anything failing, and it was: ``min_slope`` and ``min_thickness`` are scheme and geometry knobs that still surfaced as
# calibratable. The gate here is that a leaf enters the catalog only when its
# field carries a :class:`~hydromodpy.core.config_kit.calibrable.Calibrable`
# annotation, whatever its name.


class _Reach(HydroModelBase):
    """A declared quantity next to an undeclared numeric sibling."""

    manning: Annotated[float, Profile.USER] = Field(
        default=0.03, json_schema_extra=field_metadata(calibrable=Calibrable(units="s/m^(1/3)"))
    )
    min_slope: Annotated[float, Profile.USER] = Field(default=1e-4)


class _SinksSources(HydroModelBase):
    reaches: Annotated[dict[str, _Reach], Profile.USER] = Field(default_factory=dict)


class _Flow(HydroModelBase):
    sinks_sources: Annotated[_SinksSources, Profile.USER] = Field(default_factory=_SinksSources)


def _project__catalogue_declared() -> _Project:
    return _Project(_Flow(sinks_sources=_SinksSources(reaches={"r1": _Reach()})))


def test_an_annotated_leaf_is_in_the_catalogue() -> None:
    names = targets_by_name(calibration_targets(_project__catalogue_declared()))

    assert "r1.manning" in names


def test_an_unannotated_numeric_sibling_is_not() -> None:
    names = targets_by_name(calibration_targets(_project__catalogue_declared()))

    assert "r1.min_slope" not in names
    assert not any(
        target.path.endswith("min_slope")
        for target in calibration_targets(_project__catalogue_declared())
    )


# From test_the_catalogue_of_targets.py
# What a project can calibrate has to be answerable without reading the code.
#
# A parameter is declared by a dotted path into the configuration, and until now
# finding a valid one meant knowing the Pydantic tree by heart. The question a
# hydrogeologist actually asks is the other way round: what does THIS model expose
# that I could search over, what is it worth now, and in what unit.
#
# The catalog answers from the resolved configuration, so it lists the
# boundaries this project declares and the parameters it actually carries, not a
# hand-written inventory that drifts.


def _config(tmp_path, **flow: object):
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        flow=FlowConfig(**flow),
    )


@pytest.fixture
def cfg(tmp_path):
    return _config(
        tmp_path,
        param_list=["K", "Sy"],
        param={
            "K": {"field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-5}},
            "Sy": {"field": {"id": "Sy", "kind": "homogeneous", "unit": "-", "value": 0.1}},
        },
    )


class TestWhatItLists:
    def test_it_lists_every_declared_flow_parameter(self, cfg) -> None:
        found = targets_by_path(calibration_targets(cfg))

        assert "flow.param.K.field.value" in found
        assert "flow.param.Sy.field.value" in found

    def test_a_target_carries_what_the_value_is_now(self, cfg) -> None:
        target = targets_by_path(calibration_targets(cfg))["flow.param.K.field.value"]

        assert target.current == pytest.approx(1e-5)
        assert target.instance == "K"

    def test_a_target_carries_the_unit_its_neighbour_declares(self, cfg) -> None:
        target = targets_by_path(calibration_targets(cfg))["flow.param.K.field.value"]

        assert target.units == "m/s"

    def test_a_target_the_registry_knows_carries_its_physical_range(self, cfg) -> None:
        found = targets_by_path(calibration_targets(cfg))

        assert found["flow.param.K.field.value"].physical_bounds == (1e-14, 1e2)
        assert found["flow.param.Sy.field.value"].physical_bounds == (1e-4, 0.5)

    def test_a_target_the_registry_does_not_know_says_so_rather_than_guessing(
        self, tmp_path
    ) -> None:
        cfg = _config(
            tmp_path,
            param_list=["weird"],
            param={
                "weird": {
                    "field": {"id": "weird", "kind": "homogeneous", "unit": "-", "value": 3.0}
                }
            },
        )

        target = targets_by_path(calibration_targets(cfg))["flow.param.weird.field.value"]

        assert target.physical_bounds is None

    def test_a_project_declaring_nothing_lists_nothing_rather_than_failing(self, tmp_path) -> None:
        assert calibration_targets(_config(tmp_path)) is not None


class TestWhatItLeavesOut:
    def test_a_flag_is_not_a_target(self, cfg) -> None:
        """A boolean is a switch, not a value to search between two bounds."""
        paths = targets_by_path(calibration_targets(cfg))

        assert not any(isinstance(target.current, bool) for target in paths.values())

    def test_the_mesh_is_not_offered(self, cfg) -> None:
        paths = targets_by_path(calibration_targets(cfg))

        assert not any(path.startswith("mesh") for path in paths)

    def test_every_listed_path_is_one_a_parameter_may_declare(self, cfg) -> None:
        """The catalog would be a trap if it named a path the space refuses."""

        for target in calibration_targets(cfg):
            space = ParameterSpace.from_toml_mapping(
                {"p": {"bounds": [1.0, 2.0], "path": target.path}}
            )
            assert space is not None


class TestTheOrdering:
    def test_targets_come_back_in_path_order(self, cfg) -> None:
        paths = [target.path for target in calibration_targets(cfg)]

        assert paths == sorted(paths)


# From test_the_catalogue_sees_a_value_written_with_its_unit.py
# A field value can be written two ways in TOML, and the catalog sees only one.
#
# ``[flow.param.K.field] value = 1e-4`` with a sibling ``unit = "m/s"`` and
# ``value = "1e-4 m/s"`` in one string are the same declaration. A hydrogeologist
# reads both the same way; the catalog does not.
#
# ``_is_a_physical_number`` in ``hydromodpy/calibration/targets.py`` requires
# ``isinstance(value, Real)``, so a string value is filtered out of the walk
# before it ever gets a name. Nothing coerces it earlier:
# ``_validate_value`` in ``hydromodpy/spatial/field/field_param_sections.py``
# keeps a string value as a string, unlike ``_coerce_boundary_value_and_units``
# in ``hydromodpy/physics/flow/boundary_conditions.py`` (used for
# ``[flow.bc.<id>]``), which already splits a string into a float plus its unit
# before Pydantic sees it as the ``value`` field.
#
# Concretely: ``examples/projects/01_calibration/project.toml`` writes
# ``value = "1e-4 m/s"`` under ``[flow.param.K.field]``, so its ``K`` cannot be
# named ``[calibration.parameters.K]`` at all today, while the very same
# spelling under ``[flow.bc.east_side]`` is coerced and does get a target.
#
# Investigation for this test (readers of a homogeneous field's ``.value``
# across ``hydromodpy/``, and whether each survives ``.value`` becoming a plain
# float with the unit moved to the sibling ``unit``):
#
# - ``hydromodpy/spatial/field/field_param_config.py:94-100``
#   (``FieldParamConfig._enforce_physical_bounds``). Today it only runs
#   ``validate_physical_value`` when ``self.field.value`` is already
#   ``(int, float)`` and skips the check for a string, by its own admission
#   ("string payloads carry their own unit and are handled by lower-level unit
#   resolution"). Coercion survives this reader: it simply starts validating
#   what used to be silently skipped.
#
# - ``hydromodpy/spatial/field/field_param.py`` (``FieldParam.__init__`` ->
#   ``_convert_scalar_payload_to_si``, ~L204-230) via
#   ``hydromodpy/core/units/scalar.py:parse_scalar_and_unit``. This is the
#   terminal reader that turns a field into SI values for the solver. It
#   already accepts either a bare number or a ``"<number> <unit>"`` string
#   (``parse_scalar_and_unit`` documents both forms), so it survives unchanged
#   either way; the fix would only make its input always the bare-number branch.
#
# - ``hydromodpy/spatial/field/field_param_config.py:80-91``
#   (``ResolvedFieldParam._validate_value``). An exact duplicate of the
#   section validator above, reached through a *second*, independent
#   production entry point:
#   ``hydromodpy/spatial/field/field_param_io.py`` builds its merged
#   payload straight from a raw TOML section mapping and calls
#   ``validate_resolved_field_param_data`` directly, without ever going
#   through ``FieldHomogeneousSection`` / ``field_param_sections.py``. That
#   path is used by the mesh/geology demo cases
#   (``tools/cases/``, ``hydromodpy/spatial/mesh/*/examples/*``), not by the
#   project ``[flow.param.*]`` pipeline the calibration catalog walks, so it
#   does not affect the catalog either way. But fixing only
#   ``field_param_sections.py`` would leave this duplicate validator
#   accepting an un-coerced string, i.e. the asymmetry would move one level
#   down instead of closing. Coercing survives this reader (it never sees a
#   string it didn't already accept), but a full fix costs a second file, kept
#   in lockstep with the first.
#
# - ``hydromodpy/calibration/optim/parameters.py:377-395``
#   (``_apply_resolved`` / ``set_by_path`` / ``_get_by_path``), used by the
#   legacy path-based ``[calibration.parameters.<name>] path = "..."`` form.
#   ``mode="replace"`` always ``setattr``s a plain ``float(value)``: it
#   survives regardless of ``.value``'s prior type. ``mode="scale"`` reads the
#   current value with ``_get_by_path`` and calls ``float(base)`` on it: today
#   this *already breaks* for a string field ("1e-4 m/s") --
#   ``float("1e-4 m/s")`` raises and the calibration setup fails with "requires
#   a numeric base value ... got '1e-4 m/s'". Coercing ``.value`` to a plain
#   float fixes this latent bug as a side effect, it does not create a new one.
#
# - ``hydromodpy/config/dynamic_flow_examples.py`` renders TOML examples for
#   ``[flow.param.<id>.field]`` but never sets a ``value`` key, so it is
#   unaffected either way.
#
# No reader was found that requires ``.value`` to stay a string (no
# ``.split()``, no ``isinstance(..., str)`` branch whose *absence* would raise,
# no string-specific formatting). The only cost of coercing is the duplicate
# validator in ``field_param_config.py``, and coercing also fixes an
# existing crash in scale-mode calibration through the legacy path form.
#
# Decision applied: both validators now coerce ``value = "<number> <unit>"``
# into a plain float, filling a missing sibling ``unit`` or refusing one that
# disagrees, through the shared ``coerce_scalar_value_with_unit`` helper (which
# itself reuses ``parse_scalar_and_unit``, the same primitive
# ``boundary_conditions.py`` builds on for ``[flow.bc.*]``).


def _config_with_k_written_as(tmp_path, *, value: object, unit: str | None = None):
    field: dict[str, object] = {"id": "K", "kind": "homogeneous", "value": value}
    if unit is not None:
        field["unit"] = unit
    return _config(tmp_path, param_list=["K"], param={"K": {"field": field}})


class TestTheNumericFormIsSeen:
    """The control case: number plus sibling unit, the form the catalog supports."""

    def test_a_number_with_a_sibling_unit_reaches_the_catalogue(self, tmp_path) -> None:
        cfg = _config_with_k_written_as(tmp_path, value=1e-4, unit="m/s")

        found = targets_by_path(calibration_targets(cfg))

        assert "flow.param.K.field.value" in found
        assert found["flow.param.K.field.value"].current == pytest.approx(1e-4)


class TestTheStringFormIsInvisible:
    """The former asymmetry: same physical declaration, one string away, now closed."""

    def test_a_number_with_its_unit_in_one_string_also_reaches_the_catalogue(
        self, tmp_path
    ) -> None:
        cfg = _config_with_k_written_as(tmp_path, value="1e-4 m/s")

        found = targets_by_path(calibration_targets(cfg))

        assert "flow.param.K.field.value" in found
        assert found["flow.param.K.field.value"].current == pytest.approx(1e-4)

    def test_the_string_form_fills_a_missing_sibling_unit(self, tmp_path) -> None:
        cfg = _config_with_k_written_as(tmp_path, value="1e-4 m/s")

        field = cfg.flow.param["K"].field
        assert field.value == pytest.approx(1e-4)
        assert field.unit == "m/s"


class TestAConflictingUnitIsRefused:
    """Two answers to one question: the schema must pick neither, and raise."""

    def test_a_string_unit_contradicting_the_sibling_unit_is_refused(self, tmp_path) -> None:
        with pytest.raises(Exception, match="conflict"):
            _config_with_k_written_as(tmp_path, value="1e-4 m/s", unit="m/day")


# From test_the_soil_capacity_is_offered_to_the_calibration_as_soil_ru.py
# The soil reservoir offers six named targets to a calibration.
#
# Each carries the unit its own field declares, not the ``mm/day`` its
# ``FlowRechargeConfig`` parent declares for the recharge rate it replaces.
# ``impervious_fraction`` is a fraction of the area, not a knob of the numerical
# scheme, and is offered the same way ``bypass_fraction`` is: no default range,
# since it belongs to the site.


def _project() -> _Project:
    soil = SoilReservoirConfig(ru=150.0)
    recharge = FlowRechargeConfig(soil=soil)
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def test_the_soil_reservoir_offers_six_named_targets_with_their_own_units() -> None:
    by_name = targets_by_name(calibration_targets(_project()))

    assert by_name["soil.ru"].units == "mm"
    assert by_name["soil.alpha"].units == "-"
    assert by_name["soil.kc"].units == "-"
    assert by_name["soil.impervious_fraction"].units == "-"
    assert by_name["soil.bypass_fraction"].units == "-"
    assert by_name["soil.transit_time"].units == "day"


def test_impervious_fraction_declares_no_default_range() -> None:
    by_name = targets_by_name(calibration_targets(_project()))

    target = by_name["soil.impervious_fraction"]
    assert target.calibrable is not None
    assert target.calibrable.bounds is None
    assert target.registry_id == "soil_impervious_fraction"
    assert target.physical_bounds == (0.0, 0.95)


# From test_the_transit_time_does_not_borrow_a_conductivity_range.py
# A soil leaf named like a hydraulic property does not borrow its range.
#
# ``PHYSICAL_BOUNDS`` already knows ``"t"`` (transmissivity), and a bare leaf
# lookup would have handed ``soil.transit_time`` that range instead of the one a
# soil delay actually respects. ``_REGISTRY_ID_BY_PATH`` binds each soil path to
# its own ``soil_*`` key, never found by the bare leaf name.


def test_transit_time_reads_its_own_range_not_a_transmissivity() -> None:
    by_name = targets_by_name(calibration_targets(_project()))

    transit_time = by_name["soil.transit_time"]

    assert transit_time.registry_id == "soil_transit_time"
    assert transit_time.physical_bounds == (0.0, 30.0)


def test_alpha_never_answers_to_its_bare_leaf_name() -> None:
    by_name = targets_by_name(calibration_targets(_project()))

    alpha = by_name["soil.alpha"]

    assert alpha.registry_id == "soil_alpha"
    assert alpha.registry_id != "alpha"


# From test_the_vertical_profile_characteristic_depth_is_calibrable.py
# The vertical profile's characteristic_depth and min_factor are calibrable.
#
# ``flow.param.<id>.field_vertical_profile`` sits under a dict keyed by the
# parameter id ("K", "Sy", ...), so ``_registry_id_for`` sees that id as the
# walk's ``instance``. A param id of "K" or "Sy" is also a ``PHYSICAL_BOUNDS``
# key for the conductivity or the specific yield themselves: without a leaf-first
# rule for a leaf that is not its instance's headline quantity, a depth bound
# declared in meters would be faced with a conductivity range in m/s and refused
# on a unit mismatch that has nothing to do with the value.


def _project__vertical_profile(**vertical_profile: object) -> _Project:
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
        calibration_targets(
            _project__vertical_profile(kind="exponential", characteristic_depth=30.0)
        )
    )

    target = by_name["K.characteristic_depth"]
    assert target.registry_id == "characteristic_depth"
    assert target.registry_id != "k"
    assert target.units == "m"
    assert target.physical_bounds == (0.1, 1000.0)
    assert target.current == pytest.approx(30.0)


def test_min_factor_reads_its_own_range_not_k() -> None:
    by_name = targets_by_name(
        calibration_targets(
            _project__vertical_profile(
                kind="exponential", characteristic_depth=30.0, min_factor=0.2
            )
        )
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

    resolve_parameter_targets(
        calibration, _project__vertical_profile(kind="exponential", characteristic_depth=30.0)
    )

    decl = calibration.parameters["K.characteristic_depth"]
    assert decl.path == "flow.param.K.field_vertical_profile.characteristic_depth"
    assert decl.units == "m"


def test_a_bound_past_the_ceiling_is_refused_not_faced_with_k() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"K.characteristic_depth": {"bounds": [5.0, 5000.0]}}}
    )

    with pytest.raises(ConfigError, match="characteristic depth"):
        resolve_parameter_targets(
            calibration, _project__vertical_profile(kind="exponential", characteristic_depth=30.0)
        )


# The recharge factor, the rate of a well and the vertical anisotropy.
def _well(units: str) -> dict:
    return {"location": {"kind": "cell", "cell": [0, 0, 0]}, "flux": -0.01, "units": units}


@pytest.mark.parametrize(
    ("name", "units", "physical", "bounds"),
    [
        ("recharge.factor", "-", None, (0.5, 2.0)),
        ("pump.flux", "m3/s", (-1.0, 1.0), None),
        ("day.flux", "m3/day", (-86400.0, 86400.0), None),
    ],
)
def test_the_factor_and_a_well_read_their_range(name, units, physical, bounds) -> None:
    wells = {"pump": _well("m3/s"), "day": _well("m3/day")}
    project = sinks_project(recharge=FlowRechargeConfig(), wells=wells)

    target = targets_by_name(calibration_targets(project))[name]

    assert (target.units, target.physical_bounds, target.calibrable.bounds) == (
        units,
        physical,
        bounds,
    )


@pytest.mark.parametrize(
    ("param", "backend", "offered"),
    [
        (("K",), "modflow6", True),
        (("K", "Kv"), "modflow6", False),
        (("K",), "modflow_nwt", False),
    ],
)
def test_vka_is_offered_where_it_is_read(tmp_path, param, backend, offered) -> None:
    fields = {"kind": "homogeneous", "unit": "m/s", "value": 1e-5}
    declared = {name: {"field": {"id": name, **fields}} for name in param}
    cfg = _config(tmp_path, param=declared).model_copy(
        update={"solver": SolverConfig(backend={"kind": backend})}
    )

    target = targets_by_name(calibration_targets(cfg)).get("vka")

    assert (target is not None) is offered
    calibration = CalibrationConfig.model_validate({"parameters": {"vka": {"bounds": [1, 10]}}})
    if offered:
        resolve_parameter_targets(calibration, cfg)
        assert calibration.parameters["vka"].path == VKA_PATH
        assert calibration.parameters["vka"].search_space == "log"
        assert (target.current, target.units, target.physical_bounds) == (1.0, "-", (1e-3, 1e2))
    else:
        with pytest.raises(ConfigError, match="names nothing this project carries"):
            resolve_parameter_targets(calibration, cfg)
