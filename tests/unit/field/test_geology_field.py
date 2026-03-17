"""Unit tests for geology field case refactoring."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.field.geology import GeologyField, validate_geology_config_data
from hydromodpy.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.field.core.field_param import FieldParam


def _write_test_raster(path: Path):
    data = np.array(
        [
            [1.0, 1.0, 2.0, 2.0],
            [1.0, 1.0, 2.0, 2.0],
            [1.0, 1.0, 2.0, 2.0],
            [1.0, 1.0, 2.0, 2.0],
        ],
        dtype=np.float32,
    )
    transform = from_origin(0.0, 1.0, 0.25, 0.25)
    with rasterio.open(
        path,
        mode="w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        transform=transform,
        crs="EPSG:3857",
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)
    return path


def test_geology_field_from_raster_to_mesh_field(tmp_path: Path):
    raster_path = _write_test_raster(tmp_path / "geology.tif")
    field = GeologyField.from_dict(
        {
            "id": "field_geology",
            "source": {
                "path": str(raster_path),
                "kind": "raster",
            },
            "cell_samples_per_axis": 8,
        }
    )

    mesh = FieldMeshSquare.from_unit_square(target_n_cells=16, mesh_kind="structured")
    discretization = field.on_mesh(mesh, cell_samples_per_axis=8)
    assert set(discretization.zone_keys) == {"1", "2"}

    frac_sum = np.asarray(
        discretization.fractions_by_zone["1"], dtype=float
    ) + np.asarray(discretization.fractions_by_zone["2"], dtype=float)
    assert np.allclose(frac_sum, 1.0)

    param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"1": 10.0, "2": 3.0},
        field_spatial_id="field_geology",
    )
    values_mesh = param.to_mesh_field(discretization)
    values = np.asarray(values_mesh.cell_values, dtype=float)
    assert values.shape == (4, 4)
    assert np.allclose(values[:, :2], 10.0)
    assert np.allclose(values[:, 2:], 3.0)


def test_geology_config_requires_reference_raster_for_vector_source():
    with pytest.raises(ValueError, match="reference_raster_path"):
        _ = validate_geology_config_data(
            {
                "id": "field_geology",
                "source": {
                    "path": "geology.shp",
                    "kind": "vector",
                    "code_field": "CODE_LEG",
                },
            }
        )
