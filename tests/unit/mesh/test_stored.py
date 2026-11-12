"""A mesh written by the codec comes back whole, whatever engine built it."""

from __future__ import annotations

import json
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import MeshError
from hydromodpy.mesh import registry, stored
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.planar.quality import SHAPE_KEYS
from hydromodpy.mesh.request import LineFamilySpec, MeshRequest
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    LAMBERT93_WKT,
    grid_spec,
    mesh_request,
    regular_mesh,
)

X0, Y0 = L93_ORIGIN

RIVER = LineString([(X0 + 100, Y0 + 150), (X0 + 450, Y0 + 420), (X0 + 900, Y0 + 880)])
CONTACT = LineString([(X0 + 400, Y0), (X0 + 600, Y0 + 1000)])

needs_gmsh = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")


def _request(size: float = 100.0, n: int = 10) -> MeshRequest:
    """The 1 km square at Lambert-93 magnitudes, with a river and a geology contact."""
    return mesh_request(
        grid_spec(n, n, 1000.0 / n, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT),
        nominal_size_m=size,
        lines=(
            LineFamilySpec("rivers", "cell", (RIVER,)),
            LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)),
        ),
    )


def _assert_same_mesh(back, built) -> None:
    np.testing.assert_array_equal(back.mesh.vertices, built.mesh.vertices)
    np.testing.assert_array_equal(back.connectivity_rows, built.connectivity_rows)
    np.testing.assert_array_equal(back.centers, built.centers)
    assert back.mesh.cell_types == built.mesh.cell_types
    assert back.mesh.structured_shape == built.mesh.structured_shape
    assert back.structured_shape == built.structured_shape
    assert back.center_kind == built.center_kind
    assert back.crs_wkt == built.crs_wkt
    assert back.identity == built.identity
    assert back.qa.as_dict() == built.qa.as_dict()
    assert back.zone_names == built.zone_names
    assert set(back.mesh.cell_data) == set(built.mesh.cell_data)
    for name, values in built.mesh.cell_data.items():
        np.testing.assert_array_equal(back.mesh.cell_data[name], values)
    assert set(back.mesh.point_data) == set(built.mesh.point_data)
    for name, values in built.mesh.point_data.items():
        np.testing.assert_array_equal(back.mesh.point_data[name], values)
    assert len(back.cell_chains) == len(built.cell_chains)
    for chain, expected in zip(back.cell_chains, built.cell_chains, strict=True):
        assert (chain.family, chain.chain_id) == (expected.family, expected.chain_id)
        np.testing.assert_array_equal(chain.cell_ids, expected.cell_ids)
    if built.cell_zone is None:
        assert back.cell_zone is None
    else:
        np.testing.assert_array_equal(back.cell_zone, built.cell_zone)
    if built.face_families is None:
        assert back.face_families is None
    else:
        assert back.face_families.names == built.face_families.names
        for column in ("family", "cell_a", "cell_b", "node_a", "node_b", "zone_left", "zone_right"):
            np.testing.assert_array_equal(
                getattr(back.face_families, column), getattr(built.face_families, column)
            )


def test_a_regular_mesh_with_its_families_comes_back_whole(tmp_path) -> None:
    built = RegularMeshEngine().build(_request())
    assert built.cell_chains and built.face_families is not None

    stored.write_mesh(built, tmp_path / "entry")
    back = stored.read_mesh(tmp_path / "entry")

    _assert_same_mesh(back, built)


def test_a_directory_without_its_description_is_not_a_mesh(tmp_path) -> None:
    (tmp_path / "entry").mkdir()
    (tmp_path / "entry" / stored.ARRAYS_FILENAME).write_bytes(b"")

    with pytest.raises(MeshError, match="No stored mesh"):
        stored.read_mesh(tmp_path / "entry")


def test_an_entry_of_another_schema_is_refused_by_name(tmp_path) -> None:
    stored.write_mesh(RegularMeshEngine().build(_request()), tmp_path / "entry")
    description = tmp_path / "entry" / stored.DESCRIPTION_FILENAME
    description.write_text(description.read_text().replace(stored.SCHEMA_VERSION, "older"))

    with pytest.raises(MeshError, match="schema 'older'"):
        stored.read_mesh(tmp_path / "entry")


def test_an_entry_whose_arrays_are_unreadable_is_refused_by_name(tmp_path) -> None:
    stored.write_mesh(RegularMeshEngine().build(_request()), tmp_path / "entry")
    (tmp_path / "entry" / stored.ARRAYS_FILENAME).write_bytes(b"not an npz")

    with pytest.raises(MeshError, match="is unreadable: .* Delete it"):
        stored.read_mesh(tmp_path / "entry")


@pytest.mark.parametrize(
    "engine_id",
    [
        "regular",
        pytest.param("triangle", marks=needs_gmsh),
        pytest.param("voronoi", marks=needs_gmsh),
    ],
)
def test_an_entry_stored_before_the_shape_entries_is_read_with_them_measured(
    tmp_path, engine_id
) -> None:
    request = _request() if engine_id == "regular" else _request(size=60.0)
    built = registry.mesh_engines.create(engine_id).build(request)
    stored.write_mesh(built, tmp_path / "entry")
    path = tmp_path / "entry" / stored.DESCRIPTION_FILENAME
    description = json.loads(path.read_text())
    for name in SHAPE_KEYS:
        del description["qa"][name]
    path.write_text(json.dumps(description))

    back = stored.read_mesh(tmp_path / "entry")

    assert description["schema"] == stored.SCHEMA_VERSION
    _assert_same_mesh(back, built)


def test_a_mesh_without_family_and_with_node_fields_comes_back_whole(tmp_path) -> None:
    grid = regular_mesh(3, 4, dx=25.0, xmin=X0, ymin=Y0)
    built = replace(
        grid, mesh=grid.mesh.with_point_data(z=np.arange(grid.mesh.n_nodes, dtype=float))
    )
    assert built.face_families is None and built.cell_zone is None

    stored.write_mesh(built, tmp_path / "entry")

    _assert_same_mesh(stored.read_mesh(tmp_path / "entry"), built)


def test_a_mesh_with_cell_fields_comes_back_whole(tmp_path) -> None:
    grid = regular_mesh(3, 4, dx=25.0, xmin=X0, ymin=Y0)
    built = replace(
        grid, mesh=grid.mesh.with_cell_data(k=np.linspace(1e-5, 1e-4, grid.mesh.n_cells))
    )

    stored.write_mesh(built, tmp_path / "entry")

    _assert_same_mesh(stored.read_mesh(tmp_path / "entry"), built)
