"""JSON Schema export of the root configuration.

An exported schema names its dialect and a ``urn:`` identity, with no package version. A
section is picked by a dotted path, and a profile drops the fields of a higher level.
The TOML merge directives (``__append``, ``__delete``) refuse a bad value.
"""

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
from hydromodpy.schema.config_schema import (
    export_schema,
    extract_property_schema,
    schema_urn,
    write_schema,
)
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.solver.base.simulation_config import SimulationTimeConfig
from hydromodpy.solver.base.solver_config import SolverConfig


def test_export_schema_unknown_section_raises():
    with pytest.raises(ValueError):
        export_schema(HydroModPyConfig, section="not_a_real_section")


def test_write_schema_creates_valid_json_file(tmp_path: Path):
    out = tmp_path / "subdir" / "schema.json"
    written = write_schema(out, HydroModPyConfig, section="flow")
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "properties" in data
    assert "flow_regime" in data["properties"]


def test_a_dotted_path_exports_the_nested_model() -> None:
    nested = export_schema(HydroModPyConfig, section="simulation.time")

    assert nested["$id"] == schema_urn("simulation.time")
    assert set(nested["properties"]) == set(SimulationTimeConfig.model_fields)


SECTION_REFUSALS = [
    pytest.param(
        "not_a_real_section.time", "unknown config section 'not_a_real_section'", id="root segment"
    ),
    pytest.param("simulation.nowhere", "unknown field 'nowhere'", id="nested segment"),
    pytest.param("flow.flow_regime", "names a value, not a section", id="a value"),
    pytest.param("flow.bc", "names a union of 2 models", id="a union"),
]


@pytest.mark.parametrize(("section", "says"), SECTION_REFUSALS)
def test_section_refusals(section: str, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        export_schema(HydroModPyConfig, section=section)


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


MERGE_REFUSALS = [
    pytest.param({}, {"flow__append": "C"}, "requires a list value", id="append a non-list"),
    pytest.param(
        {"flow": {"process": "A"}},
        {"flow": {"process__append": ["C"]}},
        "cannot append to non-list",
        id="append to a non-list",
    ),
    pytest.param({}, {"__append": ["C"]}, "empty target key", id="append with no target"),
    pytest.param(
        {}, {"mesh__delete": False}, "requires the literal boolean true", id="delete with false"
    ),
    pytest.param({}, {"__delete": True}, "empty target key", id="delete with no target"),
]


@pytest.mark.parametrize(("base", "overlay", "says"), MERGE_REFUSALS)
def test_merge_refusals(base: dict, overlay: dict, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        merge_toml_payloads(base, overlay)


def test_a_switch_condition_is_declared_with_a_boolean() -> None:
    meta = [
        m
        for m in BathymetryReconstructionConfig.model_fields["bank_seepage"].metadata
        if isinstance(m, VisibleWhen)
    ]
    assert meta == [VisibleWhen("dynamic_area", True)]
    assert meta[0].matches(True)
    assert not meta[0].matches(False)
