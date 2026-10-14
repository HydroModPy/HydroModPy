"""The fallback reference network is the river chain the mesh of a compared run stored.

It used to be the ``river::trace`` physical group parsed out of a gmsh file. The run
stores its river cells since the cell-mesh layout: the line runs through their centres,
upstream to downstream, in the CRS of the mesh.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

import numpy as np
import pyproj
import pytest

from hydromodpy.reporting.comparison.compact_network.network import (
    fallback_reference_network,
    river_polylines,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run
from hydromodpy.results.zarr_store.mesh_layout import cell_family_rows, mesh_layout_from_cell_mesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, PlanarCellMesh
from tests._helpers.regular_cell_meshes import regular_cell_mesh


def _mesh(chains: tuple[CellChain, ...]) -> PlanarCellMesh:
    base = regular_cell_mesh(xmin=1000.0, ymin=2000.0, dx=10.0, dy=10.0, nrow=3, ncol=4)
    return dataclasses.replace(
        base, cell_chains=chains, crs_wkt=pyproj.CRS.from_epsg(2154).to_wkt()
    )


def _seal(catalog: Catalog, cell_mesh: PlanarCellMesh, *, layout: bool) -> str:
    sid = str(uuid.uuid4())
    registration = catalog.register_simulation(
        sid, project="demo", solver="modflow6", n_cells=cell_mesh.n_cells, n_layers=1
    )
    if registration.zarr is not None:
        registration.zarr.close()
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    catalog.write_mesh(
        sid,
        np.column_stack([xy, np.zeros(xy.shape[0])]),
        cell_mesh.connectivity_rows,
        np.array([0.0, -10.0]),
        layout=mesh_layout_from_cell_mesh(cell_mesh) if layout else None,
    )
    if layout:
        catalog.write_view(sid, "mesh_cell_families", cell_family_rows(cell_mesh))
    return sid


def _manifest(root: Path, project: Path, sid: str) -> None:
    """Write a comparison manifest naming the run, as the comparison launcher does."""
    item = {"id": "a", "run_folder": str(project), "sim_id": sid}
    (root / "comparison_manifest.json").write_text(json.dumps({"simulations": [item]}))


@pytest.fixture
def catalog(tmp_path: Path):
    with Catalog(tmp_path / "demo") as opened:
        yield opened


def test_a_river_chain_is_the_line_through_its_cell_centres_upstream_first(catalog):
    chains = (
        CellChain(family="rivers", chain_id=1, cell_ids=np.array([7, 6, 5])),
        CellChain(family="rivers", chain_id=0, cell_ids=np.array([0, 1, 2, 3])),
        CellChain(family="rivers", chain_id=2, cell_ids=np.array([8])),
    )
    sid = _seal(catalog, _mesh(chains), layout=True)

    lines = river_polylines(Run(sid, catalog))

    # Chain 0 along the north row, chain 1 along the middle row from east to west;
    # the chain of a single cell has no line.
    assert len(lines) == 2
    np.testing.assert_allclose(lines[0][:, 0], [1005.0, 1015.0, 1025.0, 1035.0])
    np.testing.assert_allclose(lines[0][:, 1], 2025.0)
    np.testing.assert_allclose(lines[1][:, 0], [1035.0, 1025.0, 1015.0])
    np.testing.assert_allclose(lines[1][:, 1], 2015.0)


def test_a_run_sealed_before_the_families_gives_no_line(catalog):
    sid = _seal(catalog, _mesh(()), layout=False)

    with pytest.raises(FieldNotFoundError, match="sealed before mesh families"):
        river_polylines(Run(sid, catalog))


def test_the_fallback_network_comes_from_the_runs_of_the_comparison(tmp_path):
    chain = CellChain(family="rivers", chain_id=0, cell_ids=np.array([0, 1, 2, 3]))
    with Catalog(tmp_path / "demo") as catalog:
        sid = _seal(catalog, _mesh((chain,)), layout=True)
    root = tmp_path / "comparison"
    root.mkdir()
    _manifest(root, tmp_path / "demo", sid)
    cache: dict[str, object] = {}

    network = fallback_reference_network(root, cache_ref=cache)

    assert len(network) == 1
    assert list(network["role"]) == ["reference"]
    assert network.crs.to_epsg() == 2154
    assert network.geometry.iloc[0].length == pytest.approx(30.0)
    assert fallback_reference_network(root, cache_ref=cache) is network


def test_a_comparison_of_runs_sealed_before_the_families_has_an_empty_fallback(tmp_path):
    with Catalog(tmp_path / "demo") as catalog:
        sid = _seal(catalog, _mesh(()), layout=False)
    root = tmp_path / "comparison"
    root.mkdir()
    _manifest(root, tmp_path / "demo", sid)

    assert fallback_reference_network(root, cache_ref={}).empty
