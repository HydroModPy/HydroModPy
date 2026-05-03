"""Constructor helpers for ``BoussinesqMesh``.

Splits the planar-mesh and bundle translation paths out of the dataclass so
``mesh.py`` can stay focused on the runtime API.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
    CatchmentMeshBundleCell,
    CatchmentMeshBundleEdge,
    CatchmentMeshBundleNode,
)
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    build_gmsh_support_metadata,
)
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler

from ._mesh_geometry import (
    normalize_geom_type,
    optional_finite_float,
    optional_finite_nanmean,
    polygon_area,
)

if TYPE_CHECKING:
    from .mesh import BoussinesqMesh


def build_runtime_bundle_from_planar_mesh(
    mesh: GmshPlanarMesh2D,
    *,
    domain: object,
    hydraulic_conductivity_m_s,
    storage_coefficient,
    river_trace: object | None = None,
) -> CatchmentMeshBundle:
    """Translate a runtime planar mesh into one CatchmentMeshBundle."""
    from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle import (
        _build_edge_rows,
    )

    if not isinstance(mesh, GmshPlanarMesh2D):
        raise TypeError("mesh must be a GmshPlanarMesh2D instance")
    if domain is None:
        raise ValueError("Boussinesq runtime mesh construction requires a domain")

    surface_topo = getattr(domain, "surface_topo", None)
    substratum = getattr(domain, "substratum", None)
    if surface_topo is None:
        raise ValueError("domain.surface_topo is required for runtime mesh construction")
    if substratum is None:
        raise ValueError("domain.substratum is required for runtime mesh construction")

    conductivity_values = np.asarray(
        mesh.to_cell_values(hydraulic_conductivity_m_s),
        dtype=float,
    )
    storage_values = np.asarray(
        mesh.to_cell_values(storage_coefficient),
        dtype=float,
    )

    node_x = np.asarray(mesh.points_xy[:, 0], dtype=float)
    node_y = np.asarray(mesh.points_xy[:, 1], dtype=float)
    surface_topo_sampler = PreparedSurfaceSampler.from_surface(surface_topo)
    substratum_sampler = PreparedSurfaceSampler.from_surface(substratum)
    node_z_top = surface_topo_sampler.sample(node_x, node_y).reshape(-1)
    node_z_bottom = substratum_sampler.sample(node_x, node_y).reshape(-1)
    centroid_x, centroid_y = mesh.cell_centroids()
    centroid_x = np.asarray(centroid_x, dtype=float).reshape(-1)
    centroid_y = np.asarray(centroid_y, dtype=float).reshape(-1)
    centroid_z_top = surface_topo_sampler.sample(centroid_x, centroid_y).reshape(-1)
    centroid_z_bottom = substratum_sampler.sample(centroid_x, centroid_y).reshape(-1)

    nodes = tuple(
        CatchmentMeshBundleNode(
            node_id=int(node_id),
            x=float(node_x[node_id]),
            y=float(node_y[node_id]),
            z_top=optional_finite_float(float(node_z_top[node_id])),
            z_bottom=optional_finite_float(float(node_z_bottom[node_id])),
        )
        for node_id in range(int(mesh.n_nodes))
    )

    cells: list[CatchmentMeshBundleCell] = []
    for cell in mesh.iter_cells():
        cell_index = int(cell.index)
        node_indices = tuple(int(node_id) for node_id in cell.node_indices)
        cell_node_z_top = node_z_top[np.asarray(node_indices, dtype=int)]
        cell_node_z_bottom = node_z_bottom[np.asarray(node_indices, dtype=int)]
        cells.append(
            CatchmentMeshBundleCell(
                cell_id=cell_index,
                geom_type=str(cell.kind),
                node_indices=node_indices,
                centroid_x=float(cell.centroid[0]),
                centroid_y=float(cell.centroid[1]),
                area_m2=polygon_area(np.asarray(cell.vertices, dtype=float)),
                z_top_centroid=optional_finite_float(float(centroid_z_top[cell_index])),
                z_top_mean=optional_finite_nanmean(cell_node_z_top),
                z_bottom_centroid=optional_finite_float(float(centroid_z_bottom[cell_index])),
                z_bottom_mean=optional_finite_nanmean(cell_node_z_bottom),
                geology_code=None,
                geology_key="",
                hydraulic_conductivity_m_s=float(conductivity_values[cell_index]),
                storage_coefficient=float(storage_values[cell_index]),
            )
        )

    edge_rows = _build_edge_rows(
        mesh=mesh,
        cell_zone_keys=tuple("" for _ in range(int(mesh.n_cells))),
        river_trace=river_trace,
    )
    edges = tuple(
        CatchmentMeshBundleEdge(
            edge_id=int(row["edge_id"]),
            node_a=int(row["node_a"]),
            node_b=int(row["node_b"]),
            cell_a=int(row["cell_a"]),
            cell_b=(None if str(row.get("cell_b", "")).strip() == "" else int(row["cell_b"])),
            length_m=float(row["length_m"]),
            edge_kind=str(row["edge_kind"]),
            is_river=bool(row["is_river"]),
            geology_a_key=str(row.get("geology_a_key", "")),
            geology_b_key=str(row.get("geology_b_key", "")),
        )
        for row in edge_rows
    )

    source_path = getattr(mesh, "source_path", None)
    bundle_dir = Path(source_path).resolve().parent if source_path is not None else Path.cwd()
    return CatchmentMeshBundle(
        bundle_dir=bundle_dir,
        metadata={
            "source_mesh_path": None if source_path is None else str(Path(source_path).resolve())
        },
        nodes=nodes,
        cells=tuple(cells),
        edges=edges,
        geology_fractions=(),
        mesh_summary=None,
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
        geom_type = normalize_geom_type(bundle_cell.geom_type)
        if geom_type != "triangle":
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

    edge_arrays = _assemble_edge_arrays(
        bundle=bundle,
        node_index_by_id=node_index_by_id,
        cell_index_by_id=cell_index_by_id,
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
        **edge_arrays,
        "cell_index_by_id": cell_index_by_id,
        "node_index_by_id": node_index_by_id,
        "planar_mesh": None,
        "support_metadata": build_gmsh_support_metadata(bundle),
    }


def _assemble_edge_arrays(
    *,
    bundle: CatchmentMeshBundle,
    node_index_by_id: dict[int, int],
    cell_index_by_id: dict[int, int],
    node_x: np.ndarray,
    node_y: np.ndarray,
    cell_centroid_x: np.ndarray,
    cell_centroid_y: np.ndarray,
) -> dict:
    edge_ids: list[int] = []
    edge_node_a: list[int] = []
    edge_node_b: list[int] = []
    edge_cell_a: list[int] = []
    edge_cell_b: list[int] = []
    edge_length_m: list[float] = []
    edge_distance_m: list[float] = []
    edge_midpoint_distance_to_cell_a_m: list[float] = []
    edge_midpoint_distance_to_cell_b_m: list[float] = []
    edge_midpoint_x_m: list[float] = []
    edge_midpoint_y_m: list[float] = []
    edge_kind: list[str] = []
    edge_is_river: list[bool] = []

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
        cell_a_index = int(cell_index_by_id[cell_a_id])
        cell_b_index = -1
        if bundle_edge.cell_b is not None:
            cell_b_id = int(bundle_edge.cell_b)
            if cell_b_id not in cell_index_by_id:
                raise ValueError(f"Unknown cell_b={cell_b_id} referenced by edge_id={edge_id}.")
            cell_b_index = int(cell_index_by_id[cell_b_id])

        node_a_index = int(node_index_by_id[node_a_id])
        node_b_index = int(node_index_by_id[node_b_id])
        midpoint_x = 0.5 * (node_x[node_a_index] + node_x[node_b_index])
        midpoint_y = 0.5 * (node_y[node_a_index] + node_y[node_b_index])
        dx_a_mid = midpoint_x - cell_centroid_x[cell_a_index]
        dy_a_mid = midpoint_y - cell_centroid_y[cell_a_index]
        distance_a_mid = float(np.hypot(dx_a_mid, dy_a_mid))
        distance_b_mid = np.nan
        if cell_b_index >= 0:
            dx = cell_centroid_x[cell_b_index] - cell_centroid_x[cell_a_index]
            dy = cell_centroid_y[cell_b_index] - cell_centroid_y[cell_a_index]
            dx_b_mid = midpoint_x - cell_centroid_x[cell_b_index]
            dy_b_mid = midpoint_y - cell_centroid_y[cell_b_index]
            distance_b_mid = float(np.hypot(dx_b_mid, dy_b_mid))
        else:
            dx = dx_a_mid
            dy = dy_a_mid

        edge_ids.append(edge_id)
        edge_node_a.append(node_a_id)
        edge_node_b.append(node_b_id)
        edge_cell_a.append(cell_a_index)
        edge_cell_b.append(cell_b_index)
        edge_length_m.append(float(bundle_edge.length_m))
        edge_distance_m.append(float(np.hypot(dx, dy)))
        edge_midpoint_distance_to_cell_a_m.append(distance_a_mid)
        edge_midpoint_distance_to_cell_b_m.append(distance_b_mid)
        edge_midpoint_x_m.append(float(midpoint_x))
        edge_midpoint_y_m.append(float(midpoint_y))
        edge_kind.append(str(bundle_edge.edge_kind))
        edge_is_river.append(bool(bundle_edge.is_river))

    return {
        "edge_ids": np.asarray(edge_ids, dtype=int),
        "edge_node_a": np.asarray(edge_node_a, dtype=int),
        "edge_node_b": np.asarray(edge_node_b, dtype=int),
        "edge_cell_a": np.asarray(edge_cell_a, dtype=int),
        "edge_cell_b": np.asarray(edge_cell_b, dtype=int),
        "edge_length_m": np.asarray(edge_length_m, dtype=float),
        "edge_distance_m": np.asarray(edge_distance_m, dtype=float),
        "edge_midpoint_distance_to_cell_a_m": np.asarray(
            edge_midpoint_distance_to_cell_a_m, dtype=float
        ),
        "edge_midpoint_distance_to_cell_b_m": np.asarray(
            edge_midpoint_distance_to_cell_b_m, dtype=float
        ),
        "edge_midpoint_x_m": np.asarray(edge_midpoint_x_m, dtype=float),
        "edge_midpoint_y_m": np.asarray(edge_midpoint_y_m, dtype=float),
        "edge_kind": tuple(edge_kind),
        "edge_is_river": np.asarray(edge_is_river, dtype=bool),
    }


def build_planar_mesh_kwargs(
    *,
    base_mesh: BoussinesqMesh,
    planar_mesh: GmshPlanarMesh2D,
) -> dict:
    """Return constructor kwargs for the planar-mesh BoussinesqMesh variant."""
    return {
        "bundle_dir": base_mesh.bundle_dir,
        "cell_ids": base_mesh.cell_ids,
        "node_ids": base_mesh.node_ids,
        "node_x_m": base_mesh.node_x_m,
        "node_y_m": base_mesh.node_y_m,
        "cell_node_ids": base_mesh.cell_node_ids,
        "cell_centroid_x_m": base_mesh.cell_centroid_x_m,
        "cell_centroid_y_m": base_mesh.cell_centroid_y_m,
        "cell_area_m2": base_mesh.cell_area_m2,
        "z_top_m": base_mesh.z_top_m,
        "z_bottom_m": base_mesh.z_bottom_m,
        "hydraulic_conductivity_m_s": base_mesh.hydraulic_conductivity_m_s,
        "storage_coefficient": base_mesh.storage_coefficient,
        "edge_ids": base_mesh.edge_ids,
        "edge_node_a": base_mesh.edge_node_a,
        "edge_node_b": base_mesh.edge_node_b,
        "edge_cell_a": base_mesh.edge_cell_a,
        "edge_cell_b": base_mesh.edge_cell_b,
        "edge_length_m": base_mesh.edge_length_m,
        "edge_distance_m": base_mesh.edge_distance_m,
        "edge_midpoint_distance_to_cell_a_m": base_mesh.edge_midpoint_distance_to_cell_a_m,
        "edge_midpoint_distance_to_cell_b_m": base_mesh.edge_midpoint_distance_to_cell_b_m,
        "edge_midpoint_x_m": base_mesh.edge_midpoint_x_m,
        "edge_midpoint_y_m": base_mesh.edge_midpoint_y_m,
        "edge_kind": base_mesh.edge_kind,
        "edge_is_river": base_mesh.edge_is_river,
        "cell_index_by_id": base_mesh.cell_index_by_id,
        "node_index_by_id": base_mesh.node_index_by_id,
        "planar_mesh": planar_mesh,
        "support_metadata": base_mesh.support_metadata,
    }
