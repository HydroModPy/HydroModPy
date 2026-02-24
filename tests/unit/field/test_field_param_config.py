"""Unit tests for field parameter Pydantic config validation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.field.core.field_param_config import (
    load_field_param_toml,
    validate_resolved_field_param_data,
)


def test_load_field_param_toml_validates_sections(tmp_path: Path):
    path = tmp_path / "field_param_config.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "heterogeneous"

            [field_heterogeneous]
            values = { granite = 10.0, micaschists = 2.0 }
            field_spatial_id = "field_square"
            """
        ),
        encoding="utf-8",
    )
    payload = load_field_param_toml(path)
    assert payload["field"]["id"] == "K"
    assert payload["field"]["kind"] == "heterogeneous"
    assert payload["field_heterogeneous"]["field_spatial_id"] == "field_square"


def test_load_field_param_toml_rejects_unknown_field_homogeneous_key(tmp_path: Path):
    path = tmp_path / "field_param_invalid.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "homogeneous"

            [field_homogeneous]
            value = 12.5
            unexpected = 1
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="field_homogeneous"):
        _ = load_field_param_toml(path)


def test_validate_resolved_field_param_data_accepts_homogeneous_payload():
    payload = validate_resolved_field_param_data(
        {
            "id": "K",
            "kind": "homogeneous",
            "value": 3.5,
        }
    )
    assert payload["id"] == "K"
    assert payload["kind"] == "homogeneous"
    assert float(payload["value"]) == pytest.approx(3.5)
    assert "values" not in payload


def test_load_field_param_toml_accepts_csv_values_source(tmp_path: Path):
    path = tmp_path / "field_param_csv.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "heterogeneous"

            [field_heterogeneous]
            values_source = "csv"
            values_csv_file = "mapping.csv"
            csv_key_column = "zone_key"
            csv_value_column = "value"
            field_spatial_id = "field_geology"
            """
        ),
        encoding="utf-8",
    )
    payload = load_field_param_toml(path)
    hetero = payload["field_heterogeneous"]
    assert hetero["values_source"] == "csv"
    assert hetero["values_csv_file"] == "mapping.csv"
    assert hetero["field_spatial_id"] == "field_geology"


def test_load_field_param_toml_rejects_csv_source_without_file(tmp_path: Path):
    path = tmp_path / "field_param_csv_invalid.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "heterogeneous"

            [field_heterogeneous]
            values_source = "csv"
            field_spatial_id = "field_geology"
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="values_csv_file"):
        _ = load_field_param_toml(path)
