"""Constructor helpers for ``BoussinesqMesh``.

Splits the cell-mesh and bundle translation paths out of the dataclass so
``mesh.py`` can stay focused on the runtime API. Both paths give the same
dense arrays; the edge metrics are computed once, by ``_edge_arrays``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.spatial.mesh.io.bundle import CatchmentMeshBundle
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh


def family_edge_indices(
    cell_mesh: PlanarCellMesh, family: str, edge_nodes: np.ndarray
) -> np.ndarray:
    """Return the edges of one face family, as rows of ``edge_nodes``.

    A face row names its two vertices; ``edge_nodes`` lists the two vertices of
    every edge of the caller, in the caller's order. Sorted, without repeats,
    empty when the mesh has no such family.
    """
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(family)
    if table is None or not rows.any():
        return np.empty(0, dtype=np.int64)
    geometry = cell_mesh.geometry
    edge_nodes = np.asarray(edge_nodes, dtype=np.int64)
    known = geometry.edge_ids(edge_nodes[:, 0], edge_nodes[:, 1])
    # Reversed, so an edge the caller lists twice maps to its first row.
    held = np.flatnonzero(known >= 0)[::-1]
    caller_row = np.full(geometry.edge_nodes.shape[0], -1, dtype=np.int64)
    caller_row[known[held]] = held
    wanted = geometry.edge_ids(table.node_a[rows], table.node_b[rows])
    position = np.where(wanted >= 0, caller_row[wanted], -1)
    if np.any(position < 0):
        raise ValueError(f"a face of the family '{family}' is not an edge of the mesh")
    return np.unique(position)


def mesh_arrays_from_cell_mesh(
    cell_mesh: PlanarCellMesh,
    *,
    domain: object,
    hydraulic_conductivity_m_s,
    storage_coefficient,
    source_path: Path | None = None,
) -> dict:
    """Return the dense arrays of ``BoussinesqMesh`` for a runtime planar cell mesh.

    The cells, edges, areas and lengths are those of ``cell_mesh.geometry``, the
    edges in the order of its edge table; the river edges are the faces of the
    ``rivers`` family. The top and the bottom are sampled at ``cell_mesh.centers``;
    a cell whose center falls on no data takes the mean of its finite corners.
    The cell centroid of the metric terms is the mean of the cell vertices.
    """
    if domain is None:
        raise ValueError("Boussinesq runtime mesh construction requires a domain")
    surface_topo = getattr(domain, "surface_topo", None)
    substratum = getattr(domain, "substratum", None)
    if surface_topo is None:
        raise ValueError("domain.surface_topo is required for runtime mesh construction")
    if substratum is None:
        raise ValueError("domain.substratum is required for runtime mesh construction")

    mesh = cell_mesh.mesh
    n_cells = int(mesh.n_cells)
    conductivity = _one_value_per_cell(hydraulic_conductivity_m_s, n_cells)
    storage = _one_value_per_cell(storage_coefficient, n_cells)
    cell_type = mesh.cell_types[0].value
    if cell_type != "triangle":
        raise ValueError(
            "Boussinesq V1 currently supports only triangular cells; "
            f"cell_id=0 has geom_type='{cell_type}'."
        )

    triangles = np.asarray(mesh.flat_connectivity, dtype=int)
    node_x = np.asarray(mesh.vertices[:, 0], dtype=float)
    node_y = np.asarray(mesh.vertices[:, 1], dtype=float)
    top = _sampled_at_centers(
        PreparedSurfaceSampler.from_surface(surface_topo), cell_mesh, triangles
    )
    bottom = _sampled_at_centers(
        PreparedSurfaceSampler.from_surface(substratum), cell_mesh, triangles
    )
    _check_vertical_geometry(top, bottom)

    corners = mesh.vertices[triangles]
    centroid_x = corners[:, :, 0].mean(axis=1)
    centroid_y = corners[:, :, 1].mean(axis=1)
    geometry = cell_mesh.geometry
    edge_cells = np.asarray(geometry.edge_cells, dtype=int)
    is_river = np.zeros(geometry.edge_nodes.shape[0], dtype=bool)
    is_river[family_edge_indices(cell_mesh, "rivers", geometry.edge_nodes)] = True
    edge_node_a = np.asarray(geometry.edge_nodes[:, 0], dtype=int)
    edge_node_b = np.asarray(geometry.edge_nodes[:, 1], dtype=int)
    edge_arrays = _edge_arrays(
        node_a=edge_node_a,
        node_b=edge_node_b,
        cell_a=edge_cells[:, 0],
        cell_b=np.where(edge_cells[:, 1] < 0, -1, edge_cells[:, 1]),
        node_x=node_x,
        node_y=node_y,
        cell_centroid_x=centroid_x,
        cell_centroid_y=centroid_y,
    )
    ids = np.arange(n_cells, dtype=int)
    node_ids = np.arange(mesh.n_nodes, dtype=int)
    return {
        "bundle_dir": Path(source_path).resolve().parent if source_path is not None else Path.cwd(),
        "cell_ids": ids,
        "node_ids": node_ids,
        "node_x_m": node_x,
        "node_y_m": node_y,
        "cell_node_ids": tuple(tuple(int(node) for node in row) for row in triangles.tolist()),
        "cell_centroid_x_m": centroid_x,
        "cell_centroid_y_m": centroid_y,
        "cell_area_m2": np.asarray(geometry.areas, dtype=float),
        "z_top_m": top,
        "z_bottom_m": bottom,
        "hydraulic_conductivity_m_s": conductivity,
        "storage_coefficient": storage,
        "edge_ids": np.arange(edge_cells.shape[0], dtype=int),
        "edge_node_a": edge_node_a,
        "edge_node_b": edge_node_b,
        **edge_arrays,
        "edge_length_m": np.asarray(geometry.edge_length, dtype=float),
        "edge_kind": tuple("boundary" if b < 0 else "internal" for b in edge_cells[:, 1].tolist()),
        "edge_is_river": is_river,
        "cell_index_by_id": {int(i): int(i) for i in ids.tolist()},
        "node_index_by_id": {int(i): int(i) for i in node_ids.tolist()},
    }


def _one_value_per_cell(values, n_cells: int) -> np.ndarray:
    flat = np.asarray(values, dtype=float).reshape(-1)
    if flat.size != n_cells:
        raise ValueError("Boussinesq cell values must contain exactly one value per cell")
    return flat


def _sampled_at_centers(
    sampler: PreparedSurfaceSampler, cell_mesh: PlanarCellMesh, triangles: np.ndarray
) -> np.ndarray:
    """One surface value per cell: at its center, else the mean of its finite corners."""
    centers = cell_mesh.centers
    values = np.asarray(sampler.sample(centers[:, 0], centers[:, 1]), dtype=float).reshape(-1)
    missing = np.flatnonzero(~np.isfinite(values))
    if missing.size == 0:
        return values
    vertices = cell_mesh.mesh.vertices
    corners = triangles[missing]
    at_corners = sampler.sample(vertices[corners, 0], vertices[corners, 1]).reshape(corners.shape)
    for row, cell in enumerate(missing.tolist()):
        finite = at_corners[row][np.isfinite(at_corners[row])]
        values[cell] = float(np.nanmean(finite)) if finite.size else np.nan
    return values


def _check_vertical_geometry(top: np.ndarray, bottom: np.ndarray) -> None:
    """Refuse the first cell without a top or a bottom, or whose top lies below its bottom."""
    missing = ~(np.isfinite(top) & np.isfinite(bottom))
    inverted = ~missing & (top < bottom)
    bad = np.flatnonzero(missing | inverted)
    if bad.size == 0:
        return
    cell_id = int(bad[0])
    if missing[cell_id]:
        raise ValueError(
            "Boussinesq V1 requires z_top_centroid and z_bottom_centroid "
            f"for every cell; missing values on cell_id={cell_id}."
        )
    raise ValueError(
        f"Invalid vertical geometry on cell_id={cell_id}: "
        "z_top_centroid must be >= z_bottom_centroid."
    )


def assemble_mesh_arrays_from_bundle(bundle: CatchmentMeshBundle) -> dict:
    """Translate one gmsh bundle into the dense arrays consumed by ``BoussinesqMesh``."""
    if bundle.n_cells == 0:
        raise ValueError("CatchmentMeshBundle must contain at least one cell.")
    if bundle.n_nodes == 0:
        raise ValueError("CatchmentMeshBundle must contain at least one node.")

    node_ids = np.asarray([int(node.node_id) for node in bundle.nodes], dtype=int)
    node_x = np.asarray([float(node.x) for node in bundle.nodes], dtype=float)
    node_y = np.asarray([float(node.y) for node in bundle.nodes], dtype=float)
    node_index_by_id = {int(node_id): int(index) for index, node_id in enumerate(node_ids.tolist())}

    cell_ids: list[int] = []
    cell_node_ids: list[tuple[int, ...]] = []
    cell_centroid_x: list[float] = []
    cell_centroid_y: list[float] = []
    cell_area_m2: list[float] = []
    z_top_m: list[float] = []
    z_bottom_m: list[float] = []
    hydraulic_conductivity_m_s: list[float] = []
    storage_coefficient: list[float] = []

    for bundle_cell in bundle.cells:
        cell_id = int(bundle_cell.cell_id)
        if str(bundle_cell.geom_type).strip().lower() not in {"triangle", "tri", "tri3"}:
            raise ValueError(
                "Boussinesq V1 currently supports only triangular cells; "
                f"cell_id={cell_id} has geom_type='{bundle_cell.geom_type}'."
            )
        if bundle_cell.z_top_centroid is None or bundle_cell.z_bottom_centroid is None:
            raise ValueError(
                "Boussinesq V1 requires z_top_centroid and z_bottom_centroid "
                f"for every cell; missing values on cell_id={cell_id}."
            )
        if bundle_cell.hydraulic_conductivity_m_s is None:
            raise ValueError(
                "Boussinesq V1 requires hydraulic_conductivity_m_s for every cell; "
                f"missing value on cell_id={cell_id}."
            )
        if bundle_cell.storage_coefficient is None:
            raise ValueError(
                "Boussinesq V1 requires storage_coefficient for every cell; "
                f"missing value on cell_id={cell_id}."
            )
        if float(bundle_cell.z_top_centroid) < float(bundle_cell.z_bottom_centroid):
            raise ValueError(
                f"Invalid vertical geometry on cell_id={cell_id}: "
                "z_top_centroid must be >= z_bottom_centroid."
            )
        for node_id in bundle_cell.node_indices:
            if int(node_id) not in node_index_by_id:
                raise ValueError(f"Unknown node_id={int(node_id)} referenced by cell_id={cell_id}.")

        cell_ids.append(cell_id)
        cell_node_ids.append(tuple(int(node_id) for node_id in bundle_cell.node_indices))
        cell_centroid_x.append(float(bundle_cell.centroid_x))
        cell_centroid_y.append(float(bundle_cell.centroid_y))
        cell_area_m2.append(float(bundle_cell.area_m2))
        z_top_m.append(float(bundle_cell.z_top_centroid))
        z_bottom_m.append(float(bundle_cell.z_bottom_centroid))
        hydraulic_conductivity_m_s.append(float(bundle_cell.hydraulic_conductivity_m_s))
        storage_coefficient.append(float(bundle_cell.storage_coefficient))

    cell_ids_array = np.asarray(cell_ids, dtype=int)
    cell_index_by_id = {
        int(cell_id): int(index) for index, cell_id in enumerate(cell_ids_array.tolist())
    }
    cell_centroid_x_array = np.asarray(cell_centroid_x, dtype=float)
    cell_centroid_y_array = np.asarray(cell_centroid_y, dtype=float)

    edge_ids: list[int] = []
    edge_node_a: list[int] = []
    edge_node_b: list[int] = []
    edge_cell_a: list[int] = []
    edge_cell_b: list[int] = []
    for bundle_edge in bundle.edges:
        edge_id = int(bundle_edge.edge_id)
        node_a_id = int(bundle_edge.node_a)
        node_b_id = int(bundle_edge.node_b)
        if node_a_id not in node_index_by_id or node_b_id not in node_index_by_id:
            raise ValueError(
                f"Unknown node reference on edge_id={edge_id}: ({node_a_id}, {node_b_id})."
            )
        cell_a_id = int(bundle_edge.cell_a)
        if cell_a_id not in cell_index_by_id:
            raise ValueError(f"Unknown cell_a={cell_a_id} referenced by edge_id={edge_id}.")
        cell_b_index = -1
        if bundle_edge.cell_b is not None:
            cell_b_id = int(bundle_edge.cell_b)
            if cell_b_id not in cell_index_by_id:
                raise ValueError(f"Unknown cell_b={cell_b_id} referenced by edge_id={edge_id}.")
            cell_b_index = int(cell_index_by_id[cell_b_id])
        edge_ids.append(edge_id)
        edge_node_a.append(node_a_id)
        edge_node_b.append(node_b_id)
        edge_cell_a.append(int(cell_index_by_id[cell_a_id]))
        edge_cell_b.append(cell_b_index)

    index_of_node = np.vectorize(node_index_by_id.__getitem__, otypes=[int])
    edge_arrays = _edge_arrays(
        node_a=index_of_node(np.asarray(edge_node_a, dtype=int)) if edge_ids else np.empty(0, int),
        node_b=index_of_node(np.asarray(edge_node_b, dtype=int)) if edge_ids else np.empty(0, int),
        cell_a=np.asarray(edge_cell_a, dtype=int),
        cell_b=np.asarray(edge_cell_b, dtype=int),
        node_x=node_x,
        node_y=node_y,
        cell_centroid_x=cell_centroid_x_array,
        cell_centroid_y=cell_centroid_y_array,
    )

    return {
        "bundle_dir": Path(bundle.bundle_dir),
        "cell_ids": cell_ids_array,
        "node_ids": node_ids,
        "node_x_m": node_x,
        "node_y_m": node_y,
        "cell_node_ids": tuple(cell_node_ids),
        "cell_centroid_x_m": cell_centroid_x_array,
        "cell_centroid_y_m": cell_centroid_y_array,
        "cell_area_m2": np.asarray(cell_area_m2, dtype=float),
        "z_top_m": np.asarray(z_top_m, dtype=float),
        "z_bottom_m": np.asarray(z_bottom_m, dtype=float),
        "hydraulic_conductivity_m_s": np.asarray(hydraulic_conductivity_m_s, dtype=float),
        "storage_coefficient": np.asarray(storage_coefficient, dtype=float),
        "edge_ids": np.asarray(edge_ids, dtype=int),
        **edge_arrays,
        "edge_node_a": np.asarray(edge_node_a, dtype=int),
        "edge_node_b": np.asarray(edge_node_b, dtype=int),
        "edge_length_m": np.asarray([float(e.length_m) for e in bundle.edges], dtype=float),
        "edge_kind": tuple(str(e.edge_kind) for e in bundle.edges),
        "edge_is_river": np.asarray([bool(e.is_river) for e in bundle.edges], dtype=bool),
        "cell_index_by_id": cell_index_by_id,
        "node_index_by_id": node_index_by_id,
    }


def _edge_arrays(
    *,
    node_a: np.ndarray,
    node_b: np.ndarray,
    cell_a: np.ndarray,
    cell_b: np.ndarray,
    node_x: np.ndarray,
    node_y: np.ndarray,
    cell_centroid_x: np.ndarray,
    cell_centroid_y: np.ndarray,
) -> dict:
    """The edge midpoints and the distances from cell centroids to them and between them.

    ``node_a``, ``node_b``, ``cell_a`` and ``cell_b`` are positions into the node
    and cell arrays, ``cell_b = -1`` on the boundary. A boundary edge measures its
    centroid distance to its own midpoint and has no ``cell_b`` distance.
    """
    midpoint_x = 0.5 * (node_x[node_a] + node_x[node_b])
    midpoint_y = 0.5 * (node_y[node_a] + node_y[node_b])
    dx_a_mid = midpoint_x - cell_centroid_x[cell_a]
    dy_a_mid = midpoint_y - cell_centroid_y[cell_a]
    inner = cell_b >= 0
    other = np.where(inner, cell_b, cell_a)
    dx = np.where(inner, cell_centroid_x[other] - cell_centroid_x[cell_a], dx_a_mid)
    dy = np.where(inner, cell_centroid_y[other] - cell_centroid_y[cell_a], dy_a_mid)
    distance_b_mid = np.where(
        inner,
        np.hypot(midpoint_x - cell_centroid_x[other], midpoint_y - cell_centroid_y[other]),
        np.nan,
    )
    return {
        "edge_cell_a": np.asarray(cell_a, dtype=int),
        "edge_cell_b": np.asarray(cell_b, dtype=int),
        "edge_distance_m": np.asarray(np.hypot(dx, dy), dtype=float),
        "edge_midpoint_distance_to_cell_a_m": np.asarray(np.hypot(dx_a_mid, dy_a_mid), dtype=float),
        "edge_midpoint_distance_to_cell_b_m": np.asarray(distance_b_mid, dtype=float),
        "edge_midpoint_x_m": np.asarray(midpoint_x, dtype=float),
        "edge_midpoint_y_m": np.asarray(midpoint_y, dtype=float),
    }
