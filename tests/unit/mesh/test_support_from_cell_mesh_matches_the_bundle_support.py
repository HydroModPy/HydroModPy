"""The support converted from an engine mesh answers the solver readers as the bundle support did.

Until the readers take the face families (M3), MODFLOW 6 reads a
``GmshSupportMetadata``. For the triangles of a committed bundle, the support
converted from the ``triangle`` engine mesh must answer like the one read from
the bundle CSV files; for the Voronoi dual, like the bundle support rebuilt on
the production dual. Only what a reader asks is compared: the edge order is
free.
"""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.spatial.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import load_planar_mesh
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    GmshSupportMetadata,
    build_gmsh_support_metadata,
    support_from_cell_mesh,
    support_on_planar_mesh,
)
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh, voronoi_dual_of_mesh
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
)

WKT = 'PROJCS["RGF93 / Lambert-93"]'
BUNDLES = Path(__file__).resolve().parents[3] / "validation_cases" / "shared" / "mesh_bundles"
CASES = (
    "boussinesq_circular_island_piecewise_k_irregular_tri_radial_48",
    "stream_depletion_glover_balmer_tri_refined_well",
    "linearized_unconfined_tide_irregular_tri_100x10",
    "hantush_recharge_mound_tri_conforming",
)
SIDES = ("west_side", "east_side", "south_side", "north_side")
N_PROBES = 20


def _request(bundle: Path, **options) -> MeshRequest:
    data = read_gmsh_2d_mesh(bundle / "mesh_2d.msh")
    domain = domain_polygon_from_mesh(load_planar_mesh(bundle / "mesh_2d.msh").to_hydro_mesh())
    xmin, ymin, xmax, ymax = domain.bounds
    return MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=RasterGridSpec(
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
            dx=(xmax - xmin) / 10,
            dy=(ymax - ymin) / 10,
            nrow=10,
            ncol=10,
            crs_wkt=WKT,
        ),
        nominal_size_m=10.0,
        input_triangulation=InputTriangulation(data.points_xy, data.connectivity, {}),
        options=options,
    )


def _cell_pairs(support: GmshSupportMetadata) -> np.ndarray:
    pairs = np.sort(np.column_stack([support.edge_cell_a, support.edge_cell_b]), axis=1)
    return pairs[np.lexsort(pairs.T[::-1])]


def _assert_readers_agree(ours: GmshSupportMetadata, reference: GmshSupportMetadata) -> None:
    assert ours.n_cells == reference.n_cells
    assert ours.cell_node_indices == reference.cell_node_indices
    assert np.array_equal(_cell_pairs(ours), _cell_pairs(reference))
    assert np.array_equal(ours.river_cell_indices(), reference.river_cell_indices())
    for side in SIDES:
        assert np.array_equal(
            ours.cell_indices_for_label(side), reference.cell_indices_for_label(side)
        ), side
        assert np.array_equal(
            ours.boundary_cell_indices_for_side(side),
            reference.boundary_cell_indices_for_side(side),
        ), side
    probes = np.random.default_rng(0).choice(ours.n_cells, N_PROBES, replace=False)
    for cell in probes.tolist():
        x, y = ours.cell_centroid_x_m[cell], ours.cell_centroid_y_m[cell]
        assert ours.locate_cell_index_for_point(x, y) == reference.locate_cell_index_for_point(x, y)


@pytest.mark.parametrize("case", CASES)
def test_the_triangle_support_answers_like_the_bundle_support(case: str) -> None:
    bundle = BUNDLES / case
    reference = build_gmsh_support_metadata(load_catchment_mesh_bundle(bundle))
    ours = support_from_cell_mesh(TriangleMeshEngine().build(_request(bundle)))

    _assert_readers_agree(ours, reference)
    # The CSV centres are rounded; the exact ones are those of the planar mesh reader.
    x, y = load_planar_mesh(bundle / "mesh_2d.msh").cell_centroids()
    assert np.array_equal(ours.cell_centroid_x_m, x)
    assert np.array_equal(ours.cell_centroid_y_m, y)
    assert ours.side_cell_indices == {}


@pytest.mark.parametrize("case", CASES)
def test_the_dual_support_answers_like_the_bundle_support_on_the_dual(case: str) -> None:
    bundle = BUNDLES / case
    triangulation = load_planar_mesh(bundle / "mesh_2d.msh").to_hydro_mesh()
    dual = voronoi_dual_of_mesh(triangulation, domain_polygon_from_mesh(triangulation))
    reference = support_on_planar_mesh(
        build_gmsh_support_metadata(load_catchment_mesh_bundle(bundle)), dual
    )
    ours = support_from_cell_mesh(
        VoronoiMeshEngine().build(_request(bundle, seeds="triangulation"))
    )

    _assert_readers_agree(ours, reference)
    assert np.array_equal(ours.cell_centroid_x_m, reference.cell_centroid_x_m)
    assert np.array_equal(ours.cell_centroid_y_m, reference.cell_centroid_y_m)
    assert ours.side_cell_indices.keys() == reference.side_cell_indices.keys()
    assert ours.boundary_labels_by_edge_id.keys() <= set(ours.edge_ids.tolist())


@pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")
def test_a_river_reaches_the_support_of_both_engines() -> None:
    domain = box(0.0, 0.0, 1000.0, 1000.0)
    river = LineString([(100.0, 150.0), (450.0, 420.0), (900.0, 880.0)])
    request = MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=RasterGridSpec(
            xmin=0.0,
            xmax=1000.0,
            ymin=0.0,
            ymax=1000.0,
            dx=100.0,
            dy=100.0,
            nrow=10,
            ncol=10,
            crs_wkt=WKT,
        ),
        nominal_size_m=50.0,
        lines=(LineFamilySpec("rivers", "cell", (river,)),),
    )
    triangles = TriangleMeshEngine().build(request)
    dual = VoronoiMeshEngine().build(request)
    triangle_support = support_from_cell_mesh(triangles)
    reference = support_on_planar_mesh(triangle_support, dual.mesh)

    table, rows = triangles.face_families, triangles.face_rows("rivers")
    banks = np.concatenate([table.cell_a[rows], table.cell_b[rows]])
    assert np.array_equal(triangle_support.river_cell_indices(), np.unique(banks[banks >= 0]))
    assert np.array_equal(
        support_from_cell_mesh(dual).river_cell_indices(), reference.river_cell_indices()
    )
    assert reference.river_cell_indices().size > 0
