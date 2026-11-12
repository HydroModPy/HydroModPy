from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.field_param.sections import FieldHeterogeneousSection
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.toml_io.merge import merge_toml_payloads
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
from hydromodpy.schema.config_schema import export_schema, extract_property_schema, schema_urn
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.solver.base.simulation_config import SimulationConfig
from hydromodpy.solver.base.solver_config import SolverConfig

# Tests for the JSON Schema exporter.


def test_export_schema_unknown_section_raises():
    from hydromodpy.schema.config_schema import export_schema

    with pytest.raises(ValueError):
        export_schema(HydroModPyConfig, section="not_a_real_section")


def test_write_schema_creates_valid_json_file(tmp_path: Path):
    from hydromodpy.schema.config_schema import write_schema

    out = tmp_path / "subdir" / "schema.json"
    written = write_schema(out, HydroModPyConfig, section="flow")
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "properties" in data
    assert "flow_regime" in data["properties"]


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


def test_extracting_an_absent_property_names_what_is_there() -> None:
    root = export_schema(HydroModPyConfig, section="simulation")
    with pytest.raises(KeyError, match="is not a property of this schema"):
        extract_property_schema(root, "no_such_property")


# Profile filtering and TOML merge directive semantics.


def _properties(schema: dict) -> dict:
    return schema.get("properties", {})


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


def test_export_schema_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="unknown profile"):
        export_schema(HydroModPyConfig, profile="nope")


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


def test_a_switch_condition_is_declared_with_a_boolean() -> None:
    meta = [
        m
        for m in BathymetryReconstructionConfig.model_fields["bank_seepage"].metadata
        if isinstance(m, VisibleWhen)
    ]
    assert meta == [VisibleWhen("dynamic_area", True)]
    assert meta[0].matches(True)
    assert not meta[0].matches(False)
