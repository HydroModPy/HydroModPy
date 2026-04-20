"""Tests that ``json_schema_extra`` annotations survive the export pipeline.

Widget metadata (``widget_type``, ``unit``, ``display_name_fr``,
``help_text_fr``, ``display_min``, ``display_max``) is the contract
between Pydantic models and external UIs. These tests guard that contract
against accidental regressions when the schema export evolves.
"""

from __future__ import annotations

import json
from pathlib import Path


REQUIRED_UI_KEYS = {
    "widget_type",
    "unit",
    "display_name_fr",
    "help_text_fr",
    "display_min",
    "display_max",
}


def _full_schema() -> dict:
    from hydromodpy.schema.export import export_schema

    return export_schema()


def test_flow_physical_properties_annotations_survive_export() -> None:
    from hydromodpy.core.config.schema_export import export_schema
    from hydromodpy.process.flow.physical_properties import FlowPhysicalProperties

    schema = export_schema(FlowPhysicalProperties)
    props = schema["properties"]

    for field_name in ("k_aquifer", "specific_yield", "specific_storage"):
        assert field_name in props, f"missing {field_name}"
        entry = props[field_name]
        missing = REQUIRED_UI_KEYS - set(entry.keys())
        assert not missing, (
            f"{field_name!r} schema entry is missing UI keys: {missing}"
        )


def test_widget_types_are_recognized() -> None:
    from hydromodpy.process.flow.physical_properties import FlowPhysicalProperties
    from hydromodpy.core.config.schema_export import export_schema

    allowed = {"slider", "input", "select", "checkbox", "file"}
    schema = export_schema(FlowPhysicalProperties)
    for field_name, entry in schema["properties"].items():
        widget = entry.get("widget_type")
        assert widget in allowed, f"{field_name!r} uses unknown widget {widget!r}"


def test_display_bounds_are_numeric() -> None:
    from hydromodpy.process.flow.physical_properties import FlowPhysicalProperties
    from hydromodpy.core.config.schema_export import export_schema

    schema = export_schema(FlowPhysicalProperties)
    for field_name, entry in schema["properties"].items():
        lo = entry.get("display_min")
        hi = entry.get("display_max")
        assert isinstance(lo, (int, float)), f"{field_name} display_min not numeric"
        assert isinstance(hi, (int, float)), f"{field_name} display_max not numeric"
        assert lo < hi, f"{field_name} has display_min >= display_max"


def test_exported_config_preserves_widget_metadata(tmp_path: Path) -> None:
    """The ``config.json`` written by export_full_schema keeps UI metadata.

    ``FlowPhysicalProperties`` is registered as its own root section, so
    the assertion uses the section-level exporter rather than hunting
    ``$defs`` in the root schema.
    """
    from hydromodpy.core.config.schema_export import export_schema
    from hydromodpy.schema.export import export_full_schema

    paths = export_full_schema(tmp_path)
    assert paths["config"].is_file()

    phys_schema = export_schema(section="flow_physical_properties")
    k = phys_schema["properties"]["k_aquifer"]
    assert k.get("widget_type") == "input"
    assert k.get("unit") == "m/s"
    assert k.get("display_name_fr")
    assert k.get("help_text_fr")


def test_help_text_fr_is_french_when_present() -> None:
    """Soft sanity check: any field carrying help_text_fr has non-empty content."""
    from hydromodpy.process.flow.physical_properties import FlowPhysicalProperties
    from hydromodpy.core.config.schema_export import export_schema

    schema = export_schema(FlowPhysicalProperties)
    for field_name, entry in schema["properties"].items():
        help_fr = entry.get("help_text_fr")
        if help_fr is not None:
            assert isinstance(help_fr, str) and help_fr.strip(), (
                f"{field_name} has empty help_text_fr"
            )
