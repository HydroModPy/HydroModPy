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
            unit = "m/s"

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
    assert payload["field"]["unit"] == "m/s"
    assert payload["field_heterogeneous"]["field_spatial_id"] == "field_square"


def test_load_field_param_toml_accepts_empty_inactive_mode_sections(tmp_path: Path):
    path = tmp_path / "field_param_with_empty_inactive_sections.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "heterogeneous"
            unit = "m/s"

            [field_homogeneous]

            [field_heterogeneous]
            values = { granite = 10.0, micaschists = 2.0 }
            field_spatial_id = "field_square"
            """
        ),
        encoding="utf-8",
    )
    payload = load_field_param_toml(path)
    assert payload["field"]["kind"] == "heterogeneous"
    assert payload["field"]["unit"] == "m/s"
    assert payload["field_heterogeneous"]["field_spatial_id"] == "field_square"
    assert payload["field_homogeneous"] == {}


def test_load_field_param_toml_accepts_unit_alias_for_dimensionless(tmp_path: Path):
    path = tmp_path / "field_param_unit_alias.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "Sy"
            kind = "homogeneous"
            unit = "dimensionless"

            [field_homogeneous]
            value = 0.2
            """
        ),
        encoding="utf-8",
    )
    payload = load_field_param_toml(path)
    assert payload["field"]["unit"] == "-"


def test_load_field_param_toml_accepts_hourly_k_unit(tmp_path: Path):
    path = tmp_path / "field_param_unit_hourly.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "homogeneous"
            unit = "m/h"

            [field_homogeneous]
            value = 0.01
            """
        ),
        encoding="utf-8",
    )
    payload = load_field_param_toml(path)
    assert payload["field"]["unit"] == "m/h"


def test_load_field_param_toml_rejects_unknown_unit(tmp_path: Path):
    path = tmp_path / "field_param_invalid_unit.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "homogeneous"
            unit = "foo/bar"

            [field_homogeneous]
            value = 1.0
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported field.unit"):
        _ = load_field_param_toml(path)


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


def test_load_field_param_toml_rejects_field_common_section(tmp_path: Path):
    path = tmp_path / "field_param_with_common.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "homogeneous"

            [field_common]
            id = "K"

            [field_homogeneous]
            value = 12.5
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="field_common"):
        _ = load_field_param_toml(path)


def test_validate_resolved_field_param_data_accepts_homogeneous_payload():
    payload = validate_resolved_field_param_data(
        {
            "id": "K",
            "kind": "homogeneous",
            "unit": "m/day",
            "value": 3.5,
        }
    )
    assert payload["id"] == "K"
    assert payload["kind"] == "homogeneous"
    assert payload["unit"] == "m/day"
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


def test_load_field_param_toml_accepts_vertical_profile_exponential(tmp_path: Path):
    path = tmp_path / "field_param_vertical_exp.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "homogeneous"
            value = 10.0

            [field_vertical_profile]
            mode = "exponential"
            characteristic_depth = 30.0
            """
        ),
        encoding="utf-8",
    )

    payload = load_field_param_toml(path)
    vertical = payload["field_vertical_profile"]
    assert vertical["mode"] == "exponential"
    assert float(vertical["characteristic_depth"]) == pytest.approx(30.0)


def test_load_field_param_toml_accepts_vertical_profile_exponential_with_min_factor(tmp_path: Path):
    path = tmp_path / "field_param_vertical_exp_min_factor.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "homogeneous"
            value = 10.0

            [field_vertical_profile]
            mode = "exponential"
            characteristic_depth = 30.0
            min_factor = 1e-3
            """
        ),
        encoding="utf-8",
    )

    payload = load_field_param_toml(path)
    vertical = payload["field_vertical_profile"]
    assert vertical["mode"] == "exponential"
    assert float(vertical["characteristic_depth"]) == pytest.approx(30.0)
    assert float(vertical["min_factor"]) == pytest.approx(1e-3)


def test_load_field_param_toml_rejects_vertical_profile_exponential_with_invalid_min_factor(
    tmp_path: Path,
):
    path = tmp_path / "field_param_vertical_exp_invalid_min_factor.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "homogeneous"
            value = 10.0

            [field_vertical_profile]
            mode = "exponential"
            characteristic_depth = 30.0
            min_factor = 1.2
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="min_factor"):
        _ = load_field_param_toml(path)


def test_load_field_param_toml_rejects_vertical_profile_exponential_without_depth(tmp_path: Path):
    path = tmp_path / "field_param_vertical_exp_invalid.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            id = "K"
            kind = "homogeneous"
            value = 10.0

            [field_vertical_profile]
            mode = "exponential"
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="characteristic_depth"):
        _ = load_field_param_toml(path)


def test_validate_resolved_field_param_data_accepts_vertical_profile_alias():
    payload = validate_resolved_field_param_data(
        {
            "id": "K",
            "kind": "homogeneous",
            "value": 3.5,
            "field_vertical_profile": {
                "mode": "exponential",
                "characteristic_depth": 50.0,
            },
        }
    )

    assert payload["vertical_profile"]["mode"] == "exponential"
    assert float(payload["vertical_profile"]["characteristic_depth"]) == pytest.approx(50.0)


def test_validate_resolved_field_param_data_accepts_vertical_profile_alias_with_min_factor():
    payload = validate_resolved_field_param_data(
        {
            "id": "K",
            "kind": "homogeneous",
            "value": 3.5,
            "field_vertical_profile": {
                "mode": "exponential",
                "characteristic_depth": 50.0,
                "min_factor": 0.01,
            },
        }
    )

    assert payload["vertical_profile"]["mode"] == "exponential"
    assert float(payload["vertical_profile"]["characteristic_depth"]) == pytest.approx(50.0)
    assert float(payload["vertical_profile"]["min_factor"]) == pytest.approx(0.01)


def test_validate_resolved_field_param_data_accepts_units_alias():
    payload = validate_resolved_field_param_data(
        {
            "id": "Ss",
            "kind": "homogeneous",
            "units": "1/m",
            "value": 1e-6,
        }
    )
    assert payload["unit"] == "m-1"
