"""Tests for the JSON Schema exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_export_schema_returns_dict_for_root():
    from hydromodpy.config.schema_export import export_schema

    schema = export_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema
    # Root model must expose the main top-level sections.
    for section in ("workspace", "geographic", "flow", "simulation", "solver"):
        assert section in schema["properties"], f"missing {section!r} at root"


def test_export_schema_by_section_name():
    from hydromodpy.config.schema_export import export_schema

    schema = export_schema(section="flow")
    assert isinstance(schema, dict)
    # FlowConfig exposes flow_regime etc. as properties.
    assert "properties" in schema
    assert "flow_regime" in schema["properties"]


def test_export_schema_unknown_section_raises():
    from hydromodpy.config.schema_export import export_schema

    with pytest.raises(ValueError):
        export_schema(section="not_a_real_section")


def test_flow_physical_properties_schema_has_rich_annotations():
    from hydromodpy.config.schema_export import export_schema
    from hydromodpy.physics.flow.physical_properties import FlowPhysicalProperties

    schema = export_schema(FlowPhysicalProperties)
    props = schema["properties"]

    assert "k_aquifer" in props
    assert props["k_aquifer"].get("widget_type") == "input"
    assert props["k_aquifer"].get("unit") == "m/s"
    assert "display_name_fr" in props["k_aquifer"]
    assert "help_text_fr" in props["k_aquifer"]

    assert "specific_yield" in props
    assert props["specific_yield"].get("widget_type") == "slider"
    assert "display_min" in props["specific_yield"]
    assert "display_max" in props["specific_yield"]

    assert "specific_storage" in props
    assert props["specific_storage"].get("unit") == "1/m"


def test_write_schema_creates_valid_json_file(tmp_path: Path):
    from hydromodpy.config.schema_export import write_schema

    out = tmp_path / "subdir" / "schema.json"
    written = write_schema(out, section="flow")
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "properties" in data
    assert "flow_regime" in data["properties"]


def test_root_sections_lists_expected_keys():
    from hydromodpy.config.schema_export import _ensure_root_sections
    from hydromodpy.core.config_kit.registry import root_scalar_fields

    sections = _ensure_root_sections()
    scalars = root_scalar_fields()
    # Registry derives from HydroModPyConfig.model_fields; nested
    # ``flow_physical_properties`` is reachable via FlowConfig, not as a
    # root section.
    for key in (
        "workspace",
        "geographic",
        "domain",
        "data",
        "flow",
        "simulation",
        "solver",
    ):
        assert key in sections, f"missing section {key!r}"
    assert "workflow" in scalars
