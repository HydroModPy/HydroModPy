"""Unit tests for field geometry + field parameter mapping utilities."""

from __future__ import annotations

from pathlib import Path
import textwrap

import numpy as np
import pytest

from hydromodpy.field.field import Field
from hydromodpy.field.field_mesh import FieldMesh
from hydromodpy.field.field_param import FieldParam


def test_field_param_homogeneous_from_toml(tmp_path: Path):
    path = tmp_path / "field_homogeneous.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            kind = "homogeneous"
            value = 12.5
            """
        ),
        encoding="utf-8",
    )

    param = FieldParam.from_toml(path)
    assert param.is_homogeneous
    assert float(param.to_array()) == pytest.approx(12.5)
    arr = param.to_array(shape=(2, 3))
    assert arr.shape == (2, 3)
    assert np.allclose(arr, 12.5)


def test_field_param_heterogeneous_from_toml():
    param = FieldParam.from_toml(
        "hydromodpy/field/example_field.toml",
        section="field_heterogeneous",
    )
    assert param.is_heterogeneous
    assert param.field_id == "field_square"

    field = Field(
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


def test_heterogeneous_requires_zone_ids():
    param = FieldParam(
        kind="heterogeneous",
        values_by_key={"granite": 2.0, "micaschists": 5.0},
        field_id="field_square",
    )
    with pytest.raises(ValueError, match="requires 'zone_ids'"):
        _ = param.to_array()


def test_field_from_dict_with_family_orientation():
    field = Field.from_dict(
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
        textwrap.dedent(
            """
            [field]
            id = "field_square"
            line = "axis_vertical"
            zone1_side = "negative"
            zone1_name = "granite"
            zone2_name = "micaschists"
            """
        ),
        encoding="utf-8",
    )
    field = Field.from_toml(path, section="field")
    assert field.identifier == "field_square"
    assert field.line == "axis_vertical"
    assert field.zone1_side == "negative"
    assert field.zone1_name == "granite"
    assert field.zone2_name == "micaschists"


def test_field_param_heterogeneous_requires_field_id(tmp_path: Path):
    path = tmp_path / "field_missing_id.toml"
    path.write_text(
        textwrap.dedent(
            """
            [field]
            kind = "heterogeneous"
            values = { granite = 1.0, micaschists = 3.0 }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="field_id"):
        _ = FieldParam.from_toml(path)


def test_field_to_mesh_then_param_to_value_mesh():
    mesh = FieldMesh.from_unit_square(target_n_cells=20, mesh_kind="triangular_structured")
    field = Field(
        line="diag_main",
        zone1_side="positive",
        identifier="field_square",
        zone1_name="granite",
        zone2_name="micaschists",
    )
    param = FieldParam(
        kind="heterogeneous",
        values_by_key={"granite": 10.0, "micaschists": 2.0},
        field_id="field_square",
    )

    field_discretization = field.on_mesh(mesh)
    values_mesh = param.to_mesh_field(field_discretization)

    assert field_discretization.aggregation == "weighted_average"
    assert set(field_discretization.zone_keys) == {"granite", "micaschists"}
    assert field_discretization.mesh.n_cells == mesh.n_cells
    frac_sum = (
        np.asarray(field_discretization.fractions_by_zone["granite"], dtype=float)
        + np.asarray(field_discretization.fractions_by_zone["micaschists"], dtype=float)
    )
    assert np.allclose(frac_sum, 1.0)
    assert values_mesh.n_cells == mesh.n_cells
    value_arr = np.asarray(values_mesh.cell_values, dtype=float)
    assert float(np.min(value_arr)) >= 2.0 - 1e-12
    assert float(np.max(value_arr)) <= 10.0 + 1e-12
