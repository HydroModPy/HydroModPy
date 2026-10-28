"""A geology map as a zone support, :mod:`hydromodpy.spatial.field.geology_field`.

The map is an encoded raster, 0 for nodata, and keeps its polygons when it
comes from a vector file. The regular cell mesh of the geology demo is built
by :mod:`hydromodpy.spatial.field.geology_field`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import shapely
from rasterio.transform import from_origin

from hydromodpy.core.rng import RngManager
from hydromodpy.data.variables.geology.config import validate_geology_config_data
from hydromodpy.spatial.field.cell_sampling import sample_points_in_cell
from hydromodpy.spatial.field.field_param import FieldParam
from hydromodpy.spatial.field.field_spatial import WeightedAverageFieldDiscretization
from hydromodpy.spatial.field.geology_field import GeologyField, regular_cell_mesh_over_bounds
from hydromodpy.spatial.field.mesh_cells import cell_values, mesh_cells
from hydromodpy.spatial.field.unit_square_mesh import FieldMeshSquare
from hydromodpy.spatial.field.zone_fractions import ZonePolygons
from hydromodpy.spatial.mesh.model.cell_types import CellType
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.field_cases import (
    CONTACT_X,
    geology_raster,
    planar_mesh,
    vector_geology_field,
    vector_geology_support,
    write_text,
)


def _raster_field(tmp_path: Path) -> GeologyField:
    path = geology_raster(tmp_path / "geology.tif")
    config = {
        "id": "field_geology",
        "source": {"path": str(path), "kind": "raster"},
        "cell_samples_per_axis": 8,
    }
    return GeologyField.from_dict(config)


def _reference_on_mesh(
    field: GeologyField, mesh, *, cell_samples_per_axis: int
) -> WeightedAverageFieldDiscretization:
    n_sub = max(2, int(cell_samples_per_axis))
    zone_keys = field.zone_keys
    fractions_flat = {key: np.zeros(int(mesh.n_cells), dtype=float) for key in zone_keys}

    for cell in mesh_cells(mesh):
        x_s, y_s = sample_points_in_cell(cell, n_sub_per_axis=n_sub)
        zones = np.asarray(field.zone_id(x_s, y_s), dtype=object).reshape(-1)
        valid = np.array([str(z).strip() != "" for z in zones], dtype=bool)
        n_valid = int(np.count_nonzero(valid))
        if n_valid == 0:
            continue
        zones_valid = zones[valid]
        for key in zone_keys:
            count = int(np.count_nonzero(zones_valid == key))
            fractions_flat[key][cell.index] = float(count) / float(n_valid)

    fractions_by_zone = {
        key: np.asarray(cell_values(mesh, values), dtype=float)
        for key, values in fractions_flat.items()
    }
    return WeightedAverageFieldDiscretization(
        mesh=mesh,
        field_id=field.identifier,
        zone_keys=zone_keys,
        fractions_by_zone=fractions_by_zone,
    )


def test_a_raster_geology_gives_each_cell_the_value_of_its_zone(tmp_path: Path):
    field = _raster_field(tmp_path)
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=16, mesh_kind="structured")

    discretization = field.on_mesh(mesh, cell_samples_per_axis=8)
    param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"1": 10.0, "2": 3.0},
        field_spatial_id="field_geology",
    )
    values = np.asarray(param.to_mesh_field(discretization).cell_values, dtype=float)

    assert set(discretization.zone_keys) == {"1", "2"}
    fractions = discretization.fractions_by_zone
    np.testing.assert_allclose(np.add(fractions["1"], fractions["2"]), 1.0)
    assert values.shape == (16,)
    np.testing.assert_allclose(values.reshape(4, 4)[:, :2], 10.0)
    np.testing.assert_allclose(values.reshape(4, 4)[:, 2:], 3.0)


@pytest.mark.parametrize(
    ("mesh_kind", "target_n_cells"),
    [("structured", 16), ("triangular_structured", 18), ("triangular_unstructured", 18)],
)
def test_geology_field_on_mesh_matches_reference_implementation(
    tmp_path: Path, mesh_kind, target_n_cells
):
    field = _raster_field(tmp_path)
    mesh = FieldMeshSquare.from_unit_square(
        target_n_cells=target_n_cells, mesh_kind=mesh_kind, rng_manager=RngManager(master_seed=42)
    )

    reference = _reference_on_mesh(field, mesh, cell_samples_per_axis=8)
    actual = field.on_mesh(mesh, cell_samples_per_axis=8)

    assert actual.zone_keys == reference.zone_keys
    for zone_key in actual.zone_keys:
        np.testing.assert_allclose(
            actual.fractions_by_zone[zone_key], reference.fractions_by_zone[zone_key]
        )


@pytest.mark.parametrize(
    ("cell_type", "vertices", "cells"),
    [
        (CellType.QUADRILATERAL, [[2, 2], [3, 2], [3, 3], [2, 3]], [[0, 1, 2, 3]]),
        (CellType.TRIANGLE, [[0.1, 0.1], [0.4, 0.1], [0.1, 0.4], [2, 2], [3, 2], [2, 3]], [[0, 1, 2], [3, 4, 5]]),
    ],
    ids=["quadrilaterals", "triangles"],
)  # fmt: skip
def test_a_cell_beyond_the_map_has_no_zone(tmp_path: Path, cell_type, vertices, cells):
    discretization = _raster_field(tmp_path).on_mesh(planar_mesh(vertices, cells, cell_type))

    fractions = discretization.fractions_by_zone
    np.testing.assert_array_equal(fractions["1"][-1:], [0.0])
    np.testing.assert_array_equal(fractions["2"], 0.0)
    np.testing.assert_array_equal(fractions["1"][:-1], 1.0)


def test_a_point_off_the_map_on_nodata_or_on_an_unknown_code_has_no_zone():
    field = GeologyField(
        identifier="geology",
        encoded_codes=[[9, 0, 1]],
        encoded_to_zone={1: "granite"},
        transform=from_origin(0.0, 1.0, 1.0, 1.0),
    )

    for x in (0.5, 1.5, 5.0):
        assert field.zone_id(np.array([x]), np.array([0.5])).tolist() == [""]
    assert field.zone_id(np.array([2.5, 0.5]), np.array([0.5, 0.5])).tolist() == ["granite", ""]
    with pytest.raises(ValueError, match="same shape"):
        field.zone_id(np.zeros(2), np.zeros(3))


_ONE_ZONE = ZonePolygons.from_geometries(
    [shapely.box(0.0, 0.0, 1.0, 1.0)], ["schist"], zone_keys=("schist", "granite")
)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"encoded_codes": [1, 2]}, "must be a 2D integer array"),
        ({"encoded_codes": np.zeros((0, 2))}, "cannot be empty"),
        ({"encoded_to_zone": {}}, "encoded_to_zone cannot be empty"),
        ({"encoded_to_zone": {0: "granite"}}, "keys must be positive integers"),
        ({"encoded_to_zone": {1: " "}}, "values cannot be empty"),
        ({"zone_polygons": _ONE_ZONE}, "zone keys of the field"),
    ],
    ids=[
        "one-dimensional",
        "empty",
        "no-zone",
        "zero-code",
        "blank-zone",
        "polygons-of-other-zones",
    ],
)
def test_a_geology_map_it_cannot_key_is_refused(kwargs, match):
    base = {
        "identifier": "geology",
        "encoded_codes": [[1, 2]],
        "encoded_to_zone": {1: "granite", 2: "schist"},
        "transform": from_origin(0.0, 1.0, 1.0, 1.0),
    }
    with pytest.raises(ValueError, match=match):
        GeologyField(**(base | kwargs))


def test_a_raster_geology_reads_its_toml_section(tmp_path: Path):
    path = geology_raster(tmp_path / "geology.tif")
    toml = write_text(
        tmp_path / "geology.toml",
        f'[geology]\nid = "field_geology"\ncell_samples_per_axis = 6\nsource = {{ path = "{path}", kind = "raster" }}',
    )

    field = GeologyField.from_toml(toml)

    assert field.as_dict() == {
        "id": "field_geology",
        "source_kind": "raster",
        "shape": (4, 4),
        "zone_keys": ("1", "2"),
        "default_cell_samples_per_axis": 6,
    }


def test_geology_config_requires_reference_raster_for_vector_source():
    with pytest.raises(ValueError, match="reference_raster_path"):
        validate_geology_config_data(
            {
                "id": "field_geology",
                "source": {"path": "geology.shp", "kind": "vector", "code_field": "CODE_LEG"},
            }
        )


def test_a_vector_geology_field_keeps_its_polygons_in_the_model_crs(tmp_path: Path) -> None:
    field = vector_geology_field(tmp_path)
    support = vector_geology_support()

    polygons = field.zone_polygons
    assert polygons.zone_keys == field.zone_keys == ("A", "B")
    # Reprojected back to Lambert-93 and cut to the support box.
    np.testing.assert_allclose(
        shapely.total_bounds(polygons.geometries),
        [support.xmin, support.ymin, support.xmax, support.ymax],
        atol=1e-3,
    )
    areas = {
        key: float(shapely.area(polygons.geometries[polygons.zone_index == index]).sum())
        for index, key in enumerate(polygons.zone_keys)
    }
    assert abs(areas["A"] - (CONTACT_X - support.xmin) * 3000.0) < 1.0
    assert abs(areas["B"] - (support.xmax - CONTACT_X) * 3000.0) < 1.0


def test_the_demo_cells_keep_the_aspect_ratio_of_the_box():
    mesh = regular_cell_mesh_over_bounds(
        (100.0, 200.0, 500.0, 300.0), crs_wkt=TEST_CRS_WKT, target_n_cells=100
    )

    assert mesh.n_cells == 20 * 5
    assert mesh.mesh.bounds() == (100.0, 200.0, 500.0, 300.0)
    np.testing.assert_allclose(mesh.geometry.areas, 400.0)


@pytest.mark.parametrize(
    ("bounds", "reason"),
    [((0.0, 0.0, np.inf, 1.0), "finite values"), ((0.0, 1.0, 1.0, 1.0), "ymax > ymin")],
    ids=["infinite", "flat"],
)
def test_a_demo_box_must_be_finite_and_open(bounds, reason):
    with pytest.raises(ValueError, match=reason):
        regular_cell_mesh_over_bounds(bounds, crs_wkt=TEST_CRS_WKT)
