"""An exported schema declares its dialect, its identity and its version.

A document handed to a stranger has to say what it is. Three members do it:
the dialect so a validator stops guessing the keyword set, a ``urn:`` that
names which model was exported, and the HydroModPy version that produced it.

The identity carries the profile when one filtered the document, because a
trimmed schema is a different schema: two documents that accept different
payloads may not answer to one name.
"""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from hydromodpy.config.schema_export import (
    JSON_SCHEMA_DIALECT,
    ROOT_SCOPE,
    export_schema,
    extract_property_schema,
    schema_urn,
)
from hydromodpy.core.version import __version__


def test_the_root_export_declares_dialect_identity_and_version() -> None:
    schema = export_schema()

    assert schema["$schema"] == JSON_SCHEMA_DIALECT
    assert schema["$id"] == schema_urn(ROOT_SCOPE)
    assert schema["x-hmp-version"] == __version__
    Draft202012Validator.check_schema(schema)


def test_a_section_export_is_named_after_the_section() -> None:
    assert export_schema(section="flow")["$id"] == schema_urn("flow")


def test_a_bare_model_export_is_named_after_the_model() -> None:
    from hydromodpy.physics.flow.physical_properties import FlowPhysicalProperties

    schema = export_schema(FlowPhysicalProperties)
    assert schema["$id"] == schema_urn("FlowPhysicalProperties")


def test_a_filtered_export_does_not_claim_the_identity_of_the_full_one() -> None:
    full = export_schema(section="flow")
    trimmed = export_schema(section="flow", profile="user")

    assert trimmed["$id"] == schema_urn("flow:user")
    assert trimmed["$id"] != full["$id"]


def test_an_explicit_scope_overrides_the_derived_one() -> None:
    schema = export_schema(section="flow", scope="terrain-delineate:1.0.0")
    assert schema["$id"] == schema_urn("terrain-delineate:1.0.0")


def test_a_dotted_path_exports_the_nested_model() -> None:
    from hydromodpy.simulation.planning.config import SimulationTimeConfig

    nested = export_schema(section="simulation.time")

    assert nested["$id"] == schema_urn("simulation.time")
    assert set(nested["properties"]) == set(SimulationTimeConfig.model_fields)


def test_an_unknown_root_segment_names_what_is_allowed() -> None:
    with pytest.raises(ValueError, match="unknown config section 'not_a_real_section'"):
        export_schema(section="not_a_real_section.time")


def test_an_unknown_nested_segment_names_the_model_it_looked_in() -> None:
    with pytest.raises(ValueError, match="unknown field 'nowhere'"):
        export_schema(section="simulation.nowhere")


def test_a_segment_that_names_a_value_is_refused() -> None:
    with pytest.raises(ValueError, match="names a value, not a section"):
        export_schema(section="flow.flow_regime")


def test_a_segment_that_names_a_union_names_its_variants() -> None:
    with pytest.raises(ValueError, match="names a union of 3 models"):
        export_schema(section="flow.bc")


def test_a_property_extracts_with_the_definitions_it_reaches() -> None:
    root = export_schema(section="simulation")
    extracted = extract_property_schema(root, "time")

    assert set(extracted.get("$defs", {})) <= set(root.get("$defs", {}))
    Draft202012Validator.check_schema(extracted)


def test_an_extracted_property_carries_no_definition_it_does_not_reach() -> None:
    root = export_schema(section="simulation")
    extracted = extract_property_schema(root, "time")

    assert "TransportProcessConfig" not in extracted.get("$defs", {})


def test_extracting_an_absent_property_names_what_is_there() -> None:
    root = export_schema(section="simulation")
    with pytest.raises(KeyError, match="is not a property of this schema"):
        extract_property_schema(root, "no_such_property")
