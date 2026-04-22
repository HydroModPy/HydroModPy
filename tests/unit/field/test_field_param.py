"""Unit tests for field geometry + field parameter mapping utilities."""

from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.spatial.field.cases.square.field_spatial_square import FieldSquare
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.field.core.field_spatial import Field, FieldDiscretization
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)


def test_field_param_homogeneous_from_toml(tmp_path: Path):
    path = tmp_path / "field_homogeneous.toml"
    path.write_text(
        textwrap.dedent("""
            [field]
            id = "K"
            kind = "homogeneous"
            value = 12.5
            """),
        encoding="utf-8",
    )

    param = FieldParam.from_toml(path)
    assert param.is_homogeneous
    assert param.identifier == "K"
    assert float(param.to_array()) == pytest.approx(12.5)
    arr = param.to_array(shape=(2, 3))
    assert arr.shape == (2, 3)
    assert np.allclose(arr, 12.5)


def test_field_param_homogeneous_to_mesh_field_without_spatial_discretization():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=12, mesh_kind="structured")
    param = FieldParam(identifier="K", kind="homogeneous", value=7.25)
    values_mesh = param.to_mesh_field(mesh=mesh)
    values = np.asarray(values_mesh.cell_values, dtype=float)

    assert values_mesh.n_cells == mesh.n_cells
    assert values.shape == (3, 3)
    assert np.allclose(values, 7.25)


def test_field_param_homogeneous_with_vertical_profile_exponential():
    param = FieldParam(
        identifier="K",
        kind="homogeneous",
        value=10.0,
        vertical_profile={"mode": "exponential", "characteristic_depth": 20.0},
    )

    assert float(param.vertical_factor(0.0)) == pytest.approx(1.0)
    assert float(param.to_array(depth=20.0)) == pytest.approx(10.0 * np.exp(-1.0))
    arr = param.to_array(shape=(2, 2), depth=10.0)
    assert arr.shape == (2, 2)
    assert np.allclose(arr, 10.0 * np.exp(-0.5))


def test_field_param_homogeneous_with_vertical_profile_exponential_min_factor():
    param = FieldParam(
        identifier="K",
        kind="homogeneous",
        value=10.0,
        vertical_profile={
            "mode": "exponential",
            "characteristic_depth": 5.0,
            "min_factor": 0.2,
        },
    )

    assert float(param.vertical_factor(0.0)) == pytest.approx(1.0)
    assert float(param.vertical_factor(1000.0)) == pytest.approx(0.2)
    assert float(param.to_array(depth=1000.0)) == pytest.approx(2.0)


def test_field_param_exponential_profile_rejects_invalid_min_factor():
    with pytest.raises(ValueError, match="min_factor"):
        _ = FieldParam(
            identifier="K",
            kind="homogeneous",
            value=10.0,
            vertical_profile={
                "mode": "exponential",
                "characteristic_depth": 10.0,
                "min_factor": 1.2,
            },
        )


def test_field_param_converts_k_from_m_per_day_to_si():
    param = FieldParam(
        identifier="K",
        kind="homogeneous",
        unit="m/day",
        value=8.64,
    )
    assert param.unit == "m/s"
    assert float(param.value) == pytest.approx(1e-4)


def test_field_param_converts_k_from_mm_per_day_to_si():
    param = FieldParam(
        identifier="K",
        kind="homogeneous",
        unit="mm/day",
        value=8640.0,
    )
    assert param.unit == "m/s"
    assert float(param.value) == pytest.approx(1e-4)


def test_field_param_accepts_inline_k_unit_without_explicit_field_unit():
    param = FieldParam(
        identifier="K",
        kind="homogeneous",
        value="8.64 m/day",
    )
    assert param.unit == "m/s"
    assert float(param.value) == pytest.approx(1e-4)


def test_field_param_converts_ss_from_cm_inverse_to_m_inverse():
    param = FieldParam(
        identifier="Ss",
        kind="homogeneous",
        unit="cm-1",
        value=1e-6,
    )
    assert param.unit == "m-1"
    assert float(param.value) == pytest.approx(1e-4)


def test_field_param_accepts_inline_ss_unit_without_explicit_field_unit():
    param = FieldParam(
        identifier="Ss",
        kind="homogeneous",
        value="1e-6 cm-1",
    )
    assert param.unit == "m-1"
    assert float(param.value) == pytest.approx(1e-4)


def test_field_param_accepts_inline_dimensionless_sy():
    param = FieldParam(
        identifier="Sy",
        kind="homogeneous",
        value="0.2 -",
    )
    assert param.unit == "-"
    assert float(param.value) == pytest.approx(0.2)


def test_field_param_rejects_conflicting_inline_unit_with_explicit_field_unit():
    with pytest.raises(ValueError, match="mixes conflicting units"):
        _ = FieldParam(
            identifier="K",
            kind="homogeneous",
            unit="m/day",
            value="1.0 m/s",
        )


def test_field_param_rejects_incompatible_unit_family():
    with pytest.raises(ValueError, match="Expected SI family"):
        _ = FieldParam(
            identifier="K",
            kind="homogeneous",
            unit="m-1",
            value=1.0,
        )


def test_field_param_heterogeneous_from_toml():
    param = FieldParam.from_toml("hydromodpy/spatial/field/cases/square/field_param_config.toml")
    assert param.is_heterogeneous
    assert param.identifier == "K"
    assert param.field_spatial_id == "field_square"

    field = FieldSquare(
        line="diag_main",
        zone1_side="positive",
        identifier="field_square",
        zone1_name="granite",
        zone2_name="micaschists",
    )
    x = np.array([[0.25, 0.75], [0.25, 0.75]])
    y = np.array([[0.25, 0.25], [0.75, 0.75]])
    zones = field.zone_id(x, y)
    arr = param.to_array(zone_ids=zones)
    assert arr.shape == (2, 2)
    assert np.allclose(arr, np.array([[10.0, 2.0], [10.0, 10.0]]))


def test_field_param_heterogeneous_with_vertical_profile_tabulated():
    param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 10.0, "micaschists": 4.0},
        field_spatial_id="field_square",
        vertical_profile={
            "mode": "tabulated",
            "depths": [0.0, 20.0, 40.0],
            "factors": [1.0, 0.5, 0.25],
            "interpolation": "linear",
        },
    )

    zones = np.array(["granite", "micaschists", "granite"], dtype=object)
    values = param.to_array(zone_ids=zones, depth=10.0)
    assert np.allclose(values, np.array([7.5, 3.0, 7.5], dtype=float))


def test_field_param_heterogeneous_accepts_inline_units_without_explicit_field_unit():
    param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": "10.0 m/day", "micaschists": "2.0 m/day"},
        field_spatial_id="field_square",
    )

    zones = np.array(["granite", "micaschists"], dtype=object)
    values = param.to_array(zone_ids=zones)
    assert np.allclose(values, np.array([10.0 / 86400.0, 2.0 / 86400.0], dtype=float))


def test_heterogeneous_requires_zone_ids():
    param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 2.0, "micaschists": 5.0},
        field_spatial_id="field_square",
    )
    with pytest.raises(ValueError, match="requires 'zone_ids'"):
        _ = param.to_array()


def test_heterogeneous_to_mesh_field_requires_discretization():
    param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 2.0, "micaschists": 5.0},
        field_spatial_id="field_square",
    )
    with pytest.raises(ValueError, match="field_discretization"):
        _ = param.to_mesh_field()


def test_field_from_dict_with_family_orientation():
    field = FieldSquare.from_dict(
        {
            "id": "field_square",
            "line_family": "symmetry_axis",
            "line_orientation": "horizontal",
            "zone1_side": "positive",
            "zone1_name": "granite",
            "zone2_name": "micaschists",
        }
    )
    x = np.array([[0.25, 0.75], [0.25, 0.75]])
    y = np.array([[0.25, 0.25], [0.75, 0.75]])
    zones = field.zone_id(x, y)
    assert zones.shape == (2, 2)
    assert set(np.unique(zones).tolist()) <= {"granite", "micaschists"}


def test_field_from_toml(tmp_path: Path):
    path = tmp_path / "field_geometry.toml"
    path.write_text(
        textwrap.dedent("""
            [field]
            id = "field_square"
            line = "axis_vertical"
            zone1_side = "negative"
            zone1_name = "granite"
            zone2_name = "micaschists"
            """),
        encoding="utf-8",
    )
    field = FieldSquare.from_toml(path, section="field")
    assert field.identifier == "field_square"
    assert field.line == "axis_vertical"
    assert field.zone1_side == "negative"
    assert field.zone1_name == "granite"
    assert field.zone2_name == "micaschists"


def test_field_param_heterogeneous_requires_field_spatial_id(tmp_path: Path):
    path = tmp_path / "field_missing_id.toml"
    path.write_text(
        textwrap.dedent("""
            [field]
            id = "K"
            kind = "heterogeneous"
            values = { granite = 1.0, micaschists = 3.0 }
            """),
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="field_spatial_id"):
        _ = FieldParam.from_toml(path)


def test_field_param_requires_identifier(tmp_path: Path):
    path = tmp_path / "field_missing_identifier.toml"
    path.write_text(
        textwrap.dedent("""
            [field]
            kind = "homogeneous"
            value = 1.0
            """),
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="id"):
        _ = FieldParam.from_toml(path)


def test_field_param_selects_kind_from_base_section(tmp_path: Path):
    path = tmp_path / "field_kind_select.toml"
    path.write_text(
        textwrap.dedent("""
            [field]
            id = "Sy"
            kind = "homogeneous"

            [field_homogeneous]
            value = 0.21
            """),
        encoding="utf-8",
    )
    param = FieldParam.from_toml(path)
    assert param.identifier == "Sy"
    assert param.is_homogeneous
    assert float(param.value) == pytest.approx(0.21)


def test_field_param_from_toml_with_vertical_profile_exponential(tmp_path: Path):
    path = tmp_path / "field_vertical_exp.toml"
    path.write_text(
        textwrap.dedent("""
            [field]
            id = "K"
            kind = "homogeneous"
            value = 12.0

            [field_vertical_profile]
            mode = "exponential"
            characteristic_depth = 30.0
            """),
        encoding="utf-8",
    )

    param = FieldParam.from_toml(path)
    assert param.is_homogeneous
    assert param.has_vertical_variation
    assert float(param.to_array(depth=30.0)) == pytest.approx(12.0 * np.exp(-1.0))


def test_field_param_from_toml_with_vertical_profile_exponential_characteristic_depth_unit(
    tmp_path: Path,
):
    path = tmp_path / "field_vertical_exp_units.toml"
    path.write_text(
        textwrap.dedent("""
            [field]
            id = "K"
            kind = "homogeneous"
            value = 12.0

            [field_vertical_profile]
            mode = "exponential"
            characteristic_depth = "30.0 m"
            """),
        encoding="utf-8",
    )

    param = FieldParam.from_toml(path)
    assert param.is_homogeneous
    assert param.has_vertical_variation
    assert float(param.to_array(depth=30.0)) == pytest.approx(12.0 * np.exp(-1.0))


def test_field_param_heterogeneous_from_toml_with_csv_values(tmp_path: Path):
    csv_path = tmp_path / "geology_values.csv"
    csv_path.write_text(
        textwrap.dedent("""
            zone_key,property_value
            2141,12.0
            1501,8.5
            SEA,1.0
            """).strip()
        + "\n",
        encoding="utf-8",
    )

    toml_path = tmp_path / "field_param_csv.toml"
    toml_path.write_text(
        textwrap.dedent("""
            [field]
            id = "K"
            kind = "heterogeneous"

            [field_heterogeneous]
            values_source = "csv"
            values_csv_file = "geology_values.csv"
            csv_key_column = "zone_key"
            csv_value_column = "property_value"
            field_spatial_id = "field_geology"
            """),
        encoding="utf-8",
    )

    param = FieldParam.from_toml(toml_path)
    assert param.is_heterogeneous
    assert param.field_spatial_id == "field_geology"
    assert param.values_by_key == {"2141": 12.0, "1501": 8.5, "SEA": 1.0}

    zones = np.array(["1501", "2141", "SEA"], dtype=object)
    values = param.to_array(zone_ids=zones)
    assert np.allclose(values, np.array([8.5, 12.0, 1.0], dtype=float))


def test_field_param_from_toml_with_csv_rejects_duplicate_key(tmp_path: Path):
    csv_path = tmp_path / "dup.csv"
    csv_path.write_text(
        textwrap.dedent("""
            zone_key,value
            2141,1.0
            2141,2.0
            """).strip()
        + "\n",
        encoding="utf-8",
    )
    toml_path = tmp_path / "field_param_dup.toml"
    toml_path.write_text(
        textwrap.dedent("""
            [field]
            id = "K"
            kind = "heterogeneous"

            [field_heterogeneous]
            values_source = "csv"
            values_csv_file = "dup.csv"
            csv_key_column = "zone_key"
            csv_value_column = "value"
            field_spatial_id = "field_geology"
            """),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate key"):
        _ = FieldParam.from_toml(toml_path)


def test_field_param_to_mesh_field_applies_vertical_profile():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=12, mesh_kind="structured")
    param = FieldParam(
        identifier="K",
        kind="homogeneous",
        value=7.25,
        vertical_profile={"mode": "exponential", "characteristic_depth": 30.0},
    )

    values_mesh = param.to_mesh_field(mesh=mesh, depth=30.0)
    values = np.asarray(values_mesh.cell_values, dtype=float)
    assert values.shape == (3, 3)
    assert np.allclose(values, 7.25 * np.exp(-1.0))


def test_field_to_mesh_then_param_to_value_mesh():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=20, mesh_kind="triangular_structured")
    field = FieldSquare(
        line="diag_main",
        zone1_side="positive",
        identifier="field_square",
        zone1_name="granite",
        zone2_name="micaschists",
    )
    param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 10.0, "micaschists": 2.0},
        field_spatial_id="field_square",
    )

    field_discretization = field.on_mesh(mesh)
    assert isinstance(field_discretization, WeightedAverageFieldDiscretization)
    values_mesh = param.to_mesh_field(field_discretization)

    assert field_discretization.aggregation == "weighted_average"
    assert set(field_discretization.zone_keys) == {"granite", "micaschists"}
    assert field_discretization.mesh.n_cells == mesh.n_cells
    frac_sum = np.asarray(
        field_discretization.fractions_by_zone["granite"], dtype=float
    ) + np.asarray(field_discretization.fractions_by_zone["micaschists"], dtype=float)
    assert np.allclose(frac_sum, 1.0)
    assert values_mesh.n_cells == mesh.n_cells
    value_arr = np.asarray(values_mesh.cell_values, dtype=float)
    assert float(np.min(value_arr)) >= 2.0 - 1e-12
    assert float(np.max(value_arr)) <= 10.0 + 1e-12


def test_field_base_class_is_abstract():
    with pytest.raises(TypeError):
        _ = Field(identifier="abstract_only")


def test_field_discretization_base_class_is_abstract():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="structured")
    with pytest.raises(TypeError):
        _ = FieldDiscretization(mesh=mesh, field_id="field_square")
