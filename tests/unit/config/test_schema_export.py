from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.field_param.sections import FieldHeterogeneousSection
from hydromodpy.core.config_kit.introspect import extract_profile, fields_and_tables
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.toml_io.generator import generate_toml
from hydromodpy.core.toml_io.merge import merge_toml_payloads
from hydromodpy.core.version import __version__
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.model.forcing.dated_forcing import ConstantForcing, CsvForcing
from hydromodpy.model.sinks_sources.lake import BathymetryReconstructionConfig, FlowLakeConfig
from hydromodpy.model.sinks_sources.sfr import FlowReachNetworkConfig
from hydromodpy.model.sinks_sources.wells import FlowWellConfig, FlowWellLocationAbsoluteXY
from hydromodpy.model.transport.transport_config import (
    ConcentrationTransportParametersConfig,
    Modflow6PrtParametersConfig,
    ModpathParametersConfig,
)
from hydromodpy.schema.config_schema import (
    JSON_SCHEMA_DIALECT,
    ROOT_SCOPE,
    export_schema,
    extract_property_schema,
    schema_urn,
)
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.solver.base.simulation_config import SimulationConfig
from hydromodpy.solver.base.solver_config import SolverConfig

# Tests for the JSON Schema exporter.


def test_export_schema_returns_dict_for_root():
    from hydromodpy.schema.config_schema import export_schema

    schema = export_schema(HydroModPyConfig)
    assert isinstance(schema, dict)
    assert "properties" in schema
    # Root model must expose the main top-level sections.
    for section in ("workspace", "geographic", "flow", "simulation", "solver"):
        assert section in schema["properties"], f"missing {section!r} at root"


def test_export_schema_by_section_name():
    from hydromodpy.schema.config_schema import export_schema

    schema = export_schema(HydroModPyConfig, section="flow")
    assert isinstance(schema, dict)
    # FlowConfig exposes flow_regime etc. as properties.
    assert "properties" in schema
    assert "flow_regime" in schema["properties"]


def test_model_json_schema_exposes_profile_metadata():
    from hydromodpy.config import HydroModPyConfig

    schema = HydroModPyConfig.model_json_schema()
    props = schema["properties"]

    assert props["workflow"]["x-hmp-profile"] == "user"
    defs = schema["$defs"]
    assert defs["ResultsConfig"]["properties"]["keep_per_cell_budget"]["x-hmp-profile"] == "dev"
    assert defs["Modflow6Config"]["properties"]["runtime"]["x-hmp-profile"] == "expert"
    # A named table, [solver.modflow6], is a property of its section.
    assert defs["SolverConfig"]["properties"]["modflow6"] == {
        "$ref": "#/$defs/Modflow6Config",
        "x-hmp-profile": "user",
    }


def test_export_schema_unknown_section_raises():
    from hydromodpy.schema.config_schema import export_schema

    with pytest.raises(ValueError):
        export_schema(HydroModPyConfig, section="not_a_real_section")


def test_flow_physical_properties_schema_has_rich_annotations():
    from hydromodpy.model.properties.physical_properties import FlowPhysicalProperties
    from hydromodpy.schema.config_schema import export_schema

    schema = export_schema(FlowPhysicalProperties)
    props = schema["properties"]

    assert "k_aquifer" in props
    assert props["k_aquifer"].get("widget_type") == "input"
    assert props["k_aquifer"].get("unit") == "m/s"
    assert "display_name_fr" not in props["k_aquifer"]
    assert "help_text_fr" not in props["k_aquifer"]

    assert "specific_yield" in props
    assert props["specific_yield"].get("widget_type") == "slider"
    assert "display_min" in props["specific_yield"]
    assert "display_max" in props["specific_yield"]

    assert "specific_storage" in props
    assert props["specific_storage"].get("unit") == "1/m"


def test_write_schema_creates_valid_json_file(tmp_path: Path):
    from hydromodpy.schema.config_schema import write_schema

    out = tmp_path / "subdir" / "schema.json"
    written = write_schema(out, HydroModPyConfig, section="flow")
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "properties" in data
    assert "flow_regime" in data["properties"]


def test_root_sections_lists_expected_keys():
    from hydromodpy.core.config_kit.registry import root_scalar_fields, root_sections

    sections = root_sections(HydroModPyConfig)
    scalars = root_scalar_fields(HydroModPyConfig)
    # Registry derives from HydroModPyConfig.model_fields; nested
    # ``flow_physical_properties`` is reachable via FlowConfig, not as a
    # root section.
    for key in (
        "workflow",
        "workspace",
        "geographic",
        "domain",
        "data",
        "flow",
        "simulation",
        "solver",
        "export",
    ):
        assert key in sections, f"missing section {key!r}"
    assert scalars == {}


# An exported schema declares its dialect and its identity, and no package version.
#
# A document handed to a stranger has to say what it is. Two members do it: the
# dialect so a validator stops guessing the keyword set, and a ``urn:`` that names
# which model was exported. The package version stays out, so a release that leaves
# the models alone exports the same bytes and a frontend's schema diff stays quiet.
#
# The identity carries the profile when one filtered the document, because a
# trimmed schema is a different schema: two documents that accept different
# payloads may not answer to one name.


def test_the_root_export_declares_its_dialect_and_identity_and_no_package_version() -> None:
    schema = export_schema(HydroModPyConfig)

    assert schema["$schema"] == JSON_SCHEMA_DIALECT
    assert schema["$id"] == schema_urn(ROOT_SCOPE) == "urn:hmp:schema:config"
    assert __version__ not in json.dumps(schema)
    assert "x-hmp-version" not in schema
    Draft202012Validator.check_schema(schema)


def test_a_section_export_is_named_after_the_section() -> None:
    assert export_schema(HydroModPyConfig, section="flow")["$id"] == schema_urn("flow")


def test_a_bare_model_export_is_named_after_where_the_model_is_declared() -> None:
    from hydromodpy.model.properties.physical_properties import FlowPhysicalProperties

    schema = export_schema(FlowPhysicalProperties)
    assert schema["$id"] == schema_urn(
        "model.properties.physical_properties.FlowPhysicalProperties"
    )


def test_a_filtered_export_does_not_claim_the_identity_of_the_full_one() -> None:
    full = export_schema(HydroModPyConfig, section="flow")
    trimmed = export_schema(HydroModPyConfig, section="flow", profile="user")

    assert trimmed["$id"] == schema_urn("flow:user")
    assert trimmed["$id"] != full["$id"]


def test_an_explicit_scope_overrides_the_derived_one() -> None:
    schema = export_schema(HydroModPyConfig, section="flow", scope="domain-build:1.0.0")
    assert schema["$id"] == schema_urn("domain-build:1.0.0")


def test_a_dotted_path_exports_the_nested_model() -> None:
    from hydromodpy.solver.base.simulation_config import SimulationTimeConfig

    nested = export_schema(HydroModPyConfig, section="simulation.time")

    assert nested["$id"] == schema_urn("simulation.time")
    assert set(nested["properties"]) == set(SimulationTimeConfig.model_fields)


def test_an_unknown_root_segment_names_what_is_allowed() -> None:
    with pytest.raises(ValueError, match="unknown config section 'not_a_real_section'"):
        export_schema(HydroModPyConfig, section="not_a_real_section.time")


def test_an_unknown_nested_segment_names_the_model_it_looked_in() -> None:
    with pytest.raises(ValueError, match="unknown field 'nowhere'"):
        export_schema(HydroModPyConfig, section="simulation.nowhere")


def test_a_segment_that_names_a_value_is_refused() -> None:
    with pytest.raises(ValueError, match="names a value, not a section"):
        export_schema(HydroModPyConfig, section="flow.flow_regime")


def test_a_segment_that_names_a_union_names_its_variants() -> None:
    with pytest.raises(ValueError, match="names a union of 2 models"):
        export_schema(HydroModPyConfig, section="flow.bc")


@pytest.mark.parametrize(
    "section", ["simulation..time", "simulation.time.", ".simulation.time", ""]
)
def test_a_path_with_an_empty_segment_is_refused_rather_than_normalised(section: str) -> None:
    """Dropping the empty segment would mint two identities for one document."""
    with pytest.raises(ValueError, match="empty segment"):
        export_schema(HydroModPyConfig, section=section)


def test_a_property_extracts_with_the_definitions_it_reaches() -> None:
    root = export_schema(HydroModPyConfig, section="simulation")
    extracted = extract_property_schema(root, "time")

    assert set(extracted.get("$defs", {})) <= set(root.get("$defs", {}))
    Draft202012Validator.check_schema(extracted)


def test_an_extracted_property_carries_no_definition_it_does_not_reach() -> None:
    root = export_schema(HydroModPyConfig, section="simulation")
    extracted = extract_property_schema(root, "time")

    assert "TransportProcessConfig" not in extracted.get("$defs", {})


def test_extracting_an_absent_property_names_what_is_there() -> None:
    root = export_schema(HydroModPyConfig, section="simulation")
    with pytest.raises(KeyError, match="is not a property of this schema"):
        extract_property_schema(root, "no_such_property")


def test_the_default_schema_does_not_require_what_the_loader_fills():
    """A real file never names the project root, and a synthetic support has no catchment."""
    from hydromodpy.schema.config_schema import export_schema

    schema = export_schema(HydroModPyConfig)
    defs = schema["$defs"]

    assert "workspace" not in schema.get("required", [])
    assert "project_root" not in defs["WorkspaceConfig"].get("required", [])
    assert "catchment" not in defs["GeographicConfig"].get("required", [])


# Profile filtering and TOML merge directive semantics.


def _properties(schema: dict) -> dict:
    return schema.get("properties", {})


def test_export_schema_full_includes_all_profiles() -> None:
    schema = export_schema(HydroModPyConfig)
    assert _properties(schema), "root schema must expose properties"


def test_export_schema_user_drops_dev_and_expert_fields() -> None:
    full = export_schema(HydroModPyConfig)
    user = export_schema(HydroModPyConfig, profile="user")

    assert set(_properties(user)).issubset(set(_properties(full)))
    for field_schema in _properties(user).values():
        level = field_schema.get("x-hmp-profile")
        if level is None:
            continue
        assert level in {"user"}


def test_export_schema_dev_includes_user_and_dev_fields() -> None:
    user = export_schema(HydroModPyConfig, profile="user")
    dev = export_schema(HydroModPyConfig, profile="dev")

    assert set(_properties(user)).issubset(set(_properties(dev)))
    for field_schema in _properties(dev).values():
        level = field_schema.get("x-hmp-profile")
        if level is None:
            continue
        assert level in {"user", "dev"}


def test_export_schema_expert_keeps_all_fields() -> None:
    full = export_schema(HydroModPyConfig)
    expert = export_schema(HydroModPyConfig, profile="expert")
    assert set(_properties(full)) == set(_properties(expert))


def test_export_schema_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="unknown profile"):
        export_schema(HydroModPyConfig, profile="nope")


def test_merge_replaces_lists_by_default() -> None:
    base = {"flow": {"process": ["A", "B"]}}
    overlay = {"flow": {"process": ["C"]}}
    merged = merge_toml_payloads(base, overlay)
    assert merged == {"flow": {"process": ["C"]}}


def test_merge_append_suffix_concatenates_lists() -> None:
    base = {"flow": {"process": ["A", "B"]}}
    overlay = {"flow": {"process__append": ["C"]}}
    merged = merge_toml_payloads(base, overlay)
    assert merged == {"flow": {"process": ["A", "B", "C"]}}


def test_merge_append_creates_missing_key() -> None:
    base: dict = {"flow": {}}
    overlay = {"flow": {"process__append": ["C"]}}
    merged = merge_toml_payloads(base, overlay)
    assert merged == {"flow": {"process": ["C"]}}


def test_merge_append_rejects_non_list_value() -> None:
    base: dict = {}
    overlay = {"flow__append": "C"}
    with pytest.raises(ValueError, match="requires a list value"):
        merge_toml_payloads(base, overlay)


def test_merge_append_rejects_non_list_target() -> None:
    base = {"flow": {"process": "A"}}
    overlay = {"flow": {"process__append": ["C"]}}
    with pytest.raises(ValueError, match="cannot append to non-list"):
        merge_toml_payloads(base, overlay)


def test_merge_append_rejects_empty_target() -> None:
    base: dict = {}
    overlay = {"__append": ["C"]}
    with pytest.raises(ValueError, match="empty target key"):
        merge_toml_payloads(base, overlay)


def test_merge_delete_suffix_removes_inherited_key() -> None:
    base = {"mesh": {"engine": "voronoi"}, "flow": {"K": 1.0}}
    overlay = {"mesh__delete": True}
    merged = merge_toml_payloads(base, overlay)
    assert merged == {"flow": {"K": 1.0}}


def test_merge_delete_ignores_missing_key() -> None:
    base = {"flow": {"K": 1.0}}
    overlay = {"mesh__delete": True}
    merged = merge_toml_payloads(base, overlay)
    assert merged == base


def test_merge_delete_rejects_non_true_value() -> None:
    base: dict = {}
    overlay = {"mesh__delete": False}
    with pytest.raises(ValueError, match="requires the literal boolean true"):
        merge_toml_payloads(base, overlay)


def test_merge_delete_rejects_empty_target() -> None:
    base: dict = {}
    overlay = {"__delete": True}
    with pytest.raises(ValueError, match="empty target key"):
        merge_toml_payloads(base, overlay)


# Keys a guide teaches are user keys, so the user template and reference show them.
#
# A key at the dev or expert profile is left out of ``hmp config template
# --profile user`` and folded away in the parameter reference. A guide that tells
# the reader to write such a key sends them to a key they cannot find.


TAUGHT = [
    (FlowWellConfig, ("units", "forcing")),
    (ConstantForcing, ("units",)),
    (CsvForcing, ("path_file", "date_column", "value_column", "units")),
    (FlowWellLocationAbsoluteXY, ("layer",)),
    (FlowLakeConfig, ("rainfall", "evaporation", "runoff", "inflow", "withdrawal")),
    (FlowReachNetworkConfig, ("headwater_inflow", "runoff", "rainfall", "evaporation")),
    (
        Modflow6PrtParametersConfig,
        (
            "release_zone",
            "porosity",
            "max_particles",
            "stop_time",
            "track_dir",
            "release_times",
            "track_time_step",
            "particle_cell_ids",
        ),
    ),
    (ModpathParametersConfig, ("zone_partic", "track_dir", "sel_slice")),
    (ConcentrationTransportParametersConfig, ("porosity", "sconc_init", "sconc_input")),
    (ResultsConfig, ("keep_solver_files",)),
    (SimulationConfig, ("results",)),
    (VerticalGridConfig, ("lay_decay", "lay_proportions")),
    (FieldHeterogeneousSection, ("values_csv_file", "csv_key_column", "csv_value_column")),
    (CalibrationConfig, ("persist_trial_series", "persist_iteration_detail")),
    (MeshConfig, ("engine", "cell_size", "river_cell_size", "river_band", "families")),
    (HydroModPyConfig, ("mesh",)),
    (SolverConfig, ("modflow6", "modflow_nwt")),
]


@pytest.mark.parametrize(
    ("model", "name"),
    [(model, name) for model, names in TAUGHT for name in names],
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
def test_a_taught_key_is_a_user_key(model, name) -> None:
    assert extract_profile(fields_and_tables(model)[name]) is Profile.USER


def test_the_user_template_now_shows_the_structured_layers() -> None:
    text = generate_toml(modules=["domain"], profile="user", root=HydroModPyConfig)
    assert "[domain.layers]" in text
    assert "lay_proportions" in text
    assert "mf6_newton" not in generate_toml(
        modules=["solver"], profile="user", root=HydroModPyConfig
    )


def test_a_switch_condition_is_declared_with_a_boolean() -> None:
    meta = [
        m
        for m in BathymetryReconstructionConfig.model_fields["bank_seepage"].metadata
        if isinstance(m, VisibleWhen)
    ]
    assert meta == [VisibleWhen("dynamic_area", True)]
    assert meta[0].matches(True)
    assert not meta[0].matches(False)
