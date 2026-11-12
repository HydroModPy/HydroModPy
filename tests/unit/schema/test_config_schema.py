"""Export of the config model as JSON Schema plus the metadata a front end needs.

Field metadata (``widget_type``, ``unit``, ``display_min``, ``display_max``)
set in ``json_schema_extra`` is the contract between the Pydantic models and
external UIs. The export must keep it, keep its shape, and be repeatable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.model.properties.physical_properties import FlowPhysicalProperties
from hydromodpy.schema.config_schema import (
    build_config_meta,
    build_field_validators,
    export_full_schema,
    export_schema,
)

WIDGET_TYPES = {"slider", "input", "select", "checkbox", "file"}
VALIDATOR_TYPES = {"number", "enum", "boolean", "string"}


def test_widget_types_are_recognized() -> None:
    schema = export_schema(FlowPhysicalProperties)

    for field_name, entry in schema["properties"].items():
        widget = entry.get("widget_type")
        assert widget in WIDGET_TYPES, f"{field_name!r} uses unknown widget {widget!r}"


def test_config_meta_has_sections_and_groups() -> None:
    meta = build_config_meta(ROOT_CONFIG)

    assert "sections" in meta
    # Groups are keyed by the 'group' json_schema_extra. They may be empty, the shape is fixed.
    assert isinstance(meta["groups"], dict)


def test_field_validators_have_known_types() -> None:
    validators = build_field_validators(ROOT_CONFIG)

    # flow_regime is an enum ('steady' or 'transient').
    assert validators.get("flow.flow_regime") in {"enum", "string"}
    assert any(kind in VALIDATOR_TYPES for kind in validators.values())


def test_export_is_repeatable(tmp_path: Path) -> None:
    first = export_full_schema(tmp_path / "a", root=ROOT_CONFIG)
    second = export_full_schema(tmp_path / "a", root=ROOT_CONFIG)

    assert first == second
    assert first["config"].read_text(encoding="utf-8") == second["config"].read_text(
        encoding="utf-8"
    )


def test_cli_export_writes_three_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.cli._hmp import run_hmp

    out = tmp_path / "cli_out"

    assert run_hmp(monkeypatch, "config", "schema", "--bundle", "--to", str(out)) == 0
    for name in ("config.json", "config_meta.json", "field_validators.json"):
        assert (out / name).is_file()
