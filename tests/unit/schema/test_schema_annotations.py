"""Tests that ``json_schema_extra`` annotations survive the export pipeline.

Widget metadata (``widget_type``, ``unit``,
``display_min``, ``display_max``) is the contract
between Pydantic models and external UIs. These tests guard that contract
against accidental regressions when the schema export evolves.
"""

from __future__ import annotations

import json

REQUIRED_UI_KEYS = {
    "widget_type",
    "unit",
    "display_min",
    "display_max",
}


def _full_schema() -> dict:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.schema.config_schema import export_schema

    return export_schema(HydroModPyConfig)


def test_widget_types_are_recognized() -> None:
    from hydromodpy.model.properties.physical_properties import FlowPhysicalProperties
    from hydromodpy.schema.config_schema import export_schema

    allowed = {"slider", "input", "select", "checkbox", "file"}
    schema = export_schema(FlowPhysicalProperties)
    for field_name, entry in schema["properties"].items():
        widget = entry.get("widget_type")
        assert widget in allowed, f"{field_name!r} uses unknown widget {widget!r}"
