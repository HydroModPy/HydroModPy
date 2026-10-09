"""Runtime support metadata paired with one loaded Gmsh planar mesh.

The planar mesh object stays responsible for geometry and connectivity.
This module carries only the lightweight support metadata that solver
adapters may need later for robust boundary-condition or forcing mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh

logger = get_logger(__name__)

_SIDE_IDS = ("west_side", "east_side", "south_side", "north_side")


def _point_on_segment(
    point_x_m: float,
    point_y_m: float,
    x0_m: float,
    y0_m: float,
    x1_m: float,
    y1_m: float,
    *,
    tolerance: float = 1.0e-12,
) -> bool:
    """Return True when one point lies on one segment within tolerance."""
    dx = float(x1_m) - float(x0_m)
    dy = float(y1_m) - float(y0_m)
    px = float(point_x_m) - float(x0_m)
    py = float(point_y_m) - float(y0_m)
    cross = (px * dy) - (py * dx)
    if abs(cross) > float(tolerance):
        return False
    dot = (px * dx) + (py * dy)
    if dot < -float(tolerance):
        return False
    squared_length = (dx * dx) + (dy * dy)
    if dot - squared_length > float(tolerance):
        return False
    return True


def _point_in_polygon(
    point_x_m: float,
    point_y_m: float,
    polygon_x_m: np.ndarray,
    polygon_y_m: np.ndarray,
    *,
    tolerance: float = 1.0e-12,
) -> bool:
    """Return True when one point lies inside or on the boundary of one polygon."""
    x_coords = np.asarray(polygon_x_m, dtype=float).reshape(-1)
    y_coords = np.asarray(polygon_y_m, dtype=float).reshape(-1)
    if x_coords.size < 3 or y_coords.size != x_coords.size:
        return False

    point_x_m = float(point_x_m)
    point_y_m = float(point_y_m)
    for idx in range(int(x_coords.size)):
        next_idx = (idx + 1) % int(x_coords.size)
        if _point_on_segment(
            point_x_m,
            point_y_m,
            float(x_coords[idx]),
            float(y_coords[idx]),
            float(x_coords[next_idx]),
            float(y_coords[next_idx]),
            tolerance=tolerance,
        ):
            return True

    inside = False
    for idx in range(int(x_coords.size)):
        prev_idx = (idx - 1) % int(x_coords.size)
        xi = float(x_coords[idx])
        yi = float(y_coords[idx])
        xj = float(x_coords[prev_idx])
        yj = float(y_coords[prev_idx])
        intersects = ((yi > point_y_m) != (yj > point_y_m)) and (
            point_x_m < ((xj - xi) * (point_y_m - yi) / ((yj - yi) + 1.0e-300)) + xi
        )
        if intersects:
            inside = not inside
    return inside


def _infer_boundary_labels_by_edge_id(
    *,
    edge_ids: np.ndarray,
    edge_cell_b: np.ndarray,
    edge_midpoint_x_m: np.ndarray,
    edge_midpoint_y_m: np.ndarray,
    x_min_m: float,
    x_max_m: float,
    y_min_m: float,
    y_max_m: float,
) -> dict[int, str]:
    """Infer simple side labels for boundary edges from their midpoints."""
    labels: dict[int, str] = {}
    if np.asarray(edge_ids, dtype=int).size == 0:
        return labels

    span_x = max(float(x_max_m) - float(x_min_m), 0.0)
    span_y = max(float(y_max_m) - float(y_min_m), 0.0)
    tolerance_m = max(1.0e-9, 1.0e-8 * max(span_x, span_y, 1.0))

    for edge_id, cell_b, x_mid, y_mid in zip(
        np.asarray(edge_ids, dtype=int).tolist(),
        np.asarray(edge_cell_b, dtype=int).tolist(),
        np.asarray(edge_midpoint_x_m, dtype=float).tolist(),
        np.asarray(edge_midpoint_y_m, dtype=float).tolist(),
        strict=False,
    ):
        if int(cell_b) >= 0:
            continue
        if np.isclose(float(x_mid), float(x_min_m), atol=float(tolerance_m), rtol=0.0):
            labels[int(edge_id)] = "west_side"
            continue
        if np.isclose(float(x_mid), float(x_max_m), atol=float(tolerance_m), rtol=0.0):
            labels[int(edge_id)] = "east_side"
            continue
        if np.isclose(float(y_mid), float(y_min_m), atol=float(tolerance_m), rtol=0.0):
            labels[int(edge_id)] = "south_side"
            continue
        if np.isclose(float(y_mid), float(y_max_m), atol=float(tolerance_m), rtol=0.0):
            labels[int(edge_id)] = "north_side"
    return labels


@dataclass(frozen=True, slots=True)
class GmshSupportMetadata:
    """Lightweight support metadata attached to one runtime Gmsh mesh."""

    mesh_path: Path | None = None
    bundle_dir: Path | None = None
    cell_ids: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int), repr=False)
    node_ids: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int), repr=False)
    node_x_m: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=float), repr=False)
    node_y_m: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=float), repr=False)
    cell_node_indices: tuple[tuple[int, ...], ...] = ()
    cell_centroid_x_m: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=float), repr=False
    )
    cell_centroid_y_m: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=float), repr=False
    )
    cell_z_top_m: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=float), repr=False)
    cell_z_bottom_m: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=float), repr=False
    )
    cell_hydraulic_conductivity_m_s: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=float),
        repr=False,
    )
    cell_storage_coefficient: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=float),
        repr=False,
    )
    edge_ids: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int), repr=False)
    edge_node_a_index: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=int), repr=False
    )
    edge_node_b_index: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=int), repr=False
    )
    edge_cell_a: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int), repr=False)
    edge_cell_b: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int), repr=False)
    edge_midpoint_x_m: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=float), repr=False
    )
    edge_midpoint_y_m: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=float), repr=False
    )
    edge_kind: tuple[str, ...] = ()
    edge_is_river: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=bool),
        repr=False,
    )
    geology_a_key: tuple[str, ...] = ()
    geology_b_key: tuple[str, ...] = ()
    boundary_labels_by_edge_id: dict[int, str] = field(default_factory=dict)
    # Cells that carry each outer side when the mesh fixes them (a Voronoi dual:
    # the cells centred on the side). A side left out takes the owner cells of
    # its boundary faces.
    side_cell_indices: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def n_cells(self) -> int:
        return int(np.asarray(self.cell_ids, dtype=int).size)

    @property
    def boundary_edge_mask(self) -> np.ndarray:
        edge_cell_b = np.asarray(self.edge_cell_b, dtype=int).reshape(-1)
        edge_ids = np.asarray(self.edge_ids, dtype=int).reshape(-1)
        if edge_ids.size == 0:
            return np.empty(0, dtype=bool)
        return edge_cell_b < 0

    @property
    def boundary_edge_ids(self) -> np.ndarray:
        """Return the edge ids tagged as outer boundary edges."""
        edge_ids = np.asarray(self.edge_ids, dtype=int).reshape(-1)
        if edge_ids.size == 0:
            return edge_ids
        return edge_ids[self.boundary_edge_mask]

    @property
    def river_edge_ids(self) -> np.ndarray:
        """Return the edge ids tagged as river edges."""
        edge_ids = np.asarray(self.edge_ids, dtype=int).reshape(-1)
        if edge_ids.size == 0:
            return edge_ids
        river = np.asarray(self.edge_is_river, dtype=bool).reshape(-1)
        return edge_ids[river]

    @property
    def x_min_m(self) -> float:
        return float(np.min(np.asarray(self.node_x_m, dtype=float)))

    @property
    def x_max_m(self) -> float:
        return float(np.max(np.asarray(self.node_x_m, dtype=float)))

    @property
    def y_min_m(self) -> float:
        return float(np.min(np.asarray(self.node_y_m, dtype=float)))

    @property
    def y_max_m(self) -> float:
        return float(np.max(np.asarray(self.node_y_m, dtype=float)))

    def locate_cell_index_for_point(
        self,
        x_m: float,
        y_m: float,
        *,
        allow_nearest: bool = True,
    ) -> int:
        """Return the cell index that contains one XY point."""
        point_x_m = float(x_m)
        point_y_m = float(y_m)
        node_x_m = np.asarray(self.node_x_m, dtype=float)
        node_y_m = np.asarray(self.node_y_m, dtype=float)
        for cell_index, node_indices in enumerate(self.cell_node_indices):
            polygon_indices = np.asarray(node_indices, dtype=int)
            if polygon_indices.size < 3:
                continue
            polygon_x_m = node_x_m[polygon_indices]
            polygon_y_m = node_y_m[polygon_indices]
            if _point_in_polygon(
                point_x_m,
                point_y_m,
                polygon_x_m,
                polygon_y_m,
            ):
                return int(cell_index)

        if not allow_nearest:
            raise ValueError(f"Point ({point_x_m}, {point_y_m}) is outside the gmsh mesh domain.")

        dx = np.asarray(self.cell_centroid_x_m, dtype=float) - point_x_m
        dy = np.asarray(self.cell_centroid_y_m, dtype=float) - point_y_m
        return int(np.argmin((dx * dx) + (dy * dy)))

    def river_edge_indices(self) -> np.ndarray:
        """Return the edge indices tagged as river support."""
        return np.flatnonzero(np.asarray(self.edge_is_river, dtype=bool)).astype(
            int,
            copy=False,
        )

    def river_cell_indices(self) -> np.ndarray:
        """Return unique cells touched by river-tagged edges."""
        edge_indices = self.river_edge_indices()
        if edge_indices.size == 0:
            return np.empty(0, dtype=int)
        edge_cell_a = np.asarray(self.edge_cell_a, dtype=int).reshape(-1)[edge_indices]
        edge_cell_b = np.asarray(self.edge_cell_b, dtype=int).reshape(-1)[edge_indices]
        valid_cell_b = edge_cell_b[edge_cell_b >= 0]
        if valid_cell_b.size == 0:
            return np.unique(edge_cell_a.astype(int, copy=False))
        return np.unique(
            np.concatenate(
                [
                    edge_cell_a.astype(int, copy=False),
                    valid_cell_b.astype(int, copy=False),
                ]
            )
        )

    def edge_indices_for_label(self, label: str) -> np.ndarray:
        """Return edge indices matching one explicit support label."""
        label_text = str(label).strip()
        if label_text == "":
            return np.empty(0, dtype=int)
        if label_text in {"stream", "river"}:
            return self.river_edge_indices()

        matched_edge_ids = [
            int(edge_id)
            for edge_id, edge_label in self.boundary_labels_by_edge_id.items()
            if str(edge_label) == label_text
        ]
        if not matched_edge_ids:
            return np.empty(0, dtype=int)
        edge_ids = np.asarray(self.edge_ids, dtype=int).reshape(-1)
        return np.flatnonzero(np.isin(edge_ids, np.asarray(matched_edge_ids, dtype=int))).astype(
            int,
            copy=False,
        )

    def cell_indices_for_label(self, label: str) -> np.ndarray:
        """Return unique cells touched by one explicit support label."""
        label_text = str(label).strip()
        if label_text == "":
            return np.empty(0, dtype=int)
        if label_text in {"stream", "river"}:
            return self.river_cell_indices()
        if label_text in self.side_cell_indices:
            return np.asarray(self.side_cell_indices[label_text], dtype=int).copy()

        edge_indices = self.edge_indices_for_label(label_text)
        if edge_indices.size == 0:
            return np.empty(0, dtype=int)
        edge_cell_a = np.asarray(self.edge_cell_a, dtype=int).reshape(-1)[edge_indices]
        edge_cell_b = np.asarray(self.edge_cell_b, dtype=int).reshape(-1)[edge_indices]
        valid_cell_b = edge_cell_b[edge_cell_b >= 0]
        if valid_cell_b.size == 0:
            return np.unique(edge_cell_a.astype(int, copy=False))
        return np.unique(
            np.concatenate(
                [
                    edge_cell_a.astype(int, copy=False),
                    valid_cell_b.astype(int, copy=False),
                ]
            )
        )

    def boundary_edge_indices_for_side(
        self,
        bc_id: str,
        *,
        tolerance_m: float | None = None,
    ) -> np.ndarray:
        """Return boundary edges that geometrically belong to one outer side."""
        boundary_mask = np.asarray(self.boundary_edge_mask, dtype=bool)
        if boundary_mask.size == 0:
            return np.empty(0, dtype=int)

        if tolerance_m is None:
            span_x = max(self.x_max_m - self.x_min_m, 0.0)
            span_y = max(self.y_max_m - self.y_min_m, 0.0)
            tolerance_m = max(1.0e-9, 1.0e-8 * max(span_x, span_y, 1.0))

        edge_midpoint_x_m = np.asarray(self.edge_midpoint_x_m, dtype=float)
        edge_midpoint_y_m = np.asarray(self.edge_midpoint_y_m, dtype=float)
        if bc_id == "west_side":
            side_mask = np.isclose(
                edge_midpoint_x_m,
                self.x_min_m,
                atol=float(tolerance_m),
                rtol=0.0,
            )
        elif bc_id == "east_side":
            side_mask = np.isclose(
                edge_midpoint_x_m,
                self.x_max_m,
                atol=float(tolerance_m),
                rtol=0.0,
            )
        elif bc_id == "south_side":
            side_mask = np.isclose(
                edge_midpoint_y_m,
                self.y_min_m,
                atol=float(tolerance_m),
                rtol=0.0,
            )
        elif bc_id == "north_side":
            side_mask = np.isclose(
                edge_midpoint_y_m,
                self.y_max_m,
                atol=float(tolerance_m),
                rtol=0.0,
            )
        else:
            raise ValueError(f"Unsupported side boundary id: {bc_id}.")
        return np.flatnonzero(boundary_mask & side_mask).astype(int, copy=False)

    def boundary_cell_indices_for_side(
        self,
        bc_id: str,
        *,
        tolerance_m: float | None = None,
    ) -> np.ndarray:
        """Return the cells that carry one side boundary.

        The cells fixed in ``side_cell_indices`` when the side is there, else the
        unique owner cells of the side boundary faces.
        """
        if bc_id in self.side_cell_indices:
            return np.asarray(self.side_cell_indices[bc_id], dtype=int).copy()
        edge_indices = self.boundary_edge_indices_for_side(
            bc_id,
            tolerance_m=tolerance_m,
        )
        if edge_indices.size == 0:
            return np.empty(0, dtype=int)
        owner_cells = np.asarray(self.edge_cell_a, dtype=int).reshape(-1)[edge_indices]
        return np.unique(owner_cells.astype(int, copy=False))


def build_gmsh_support_metadata(bundle: object | None) -> GmshSupportMetadata | None:
    """Build runtime support metadata from one catchment mesh bundle."""
    if bundle is None:
        return None

    nodes = tuple(getattr(bundle, "nodes", ()) or ())
    cells = tuple(getattr(bundle, "cells", ()) or ())
    edges = tuple(getattr(bundle, "edges", ()) or ())

    node_ids = np.asarray([int(node.node_id) for node in nodes], dtype=int)
    node_index_by_id = {int(node_id): int(index) for index, node_id in enumerate(node_ids.tolist())}
    node_x_m = np.asarray([float(node.x) for node in nodes], dtype=float)
    node_y_m = np.asarray([float(node.y) for node in nodes], dtype=float)

    cell_ids = np.asarray([int(cell.cell_id) for cell in cells], dtype=int)
    cell_index_by_id = {int(cell_id): int(index) for index, cell_id in enumerate(cell_ids.tolist())}
    cell_node_indices = tuple(
        tuple(node_index_by_id[int(node_id)] for node_id in tuple(cell.node_indices))
        for cell in cells
    )
    cell_centroid_x_m = np.asarray([float(cell.centroid_x) for cell in cells], dtype=float)
    cell_centroid_y_m = np.asarray([float(cell.centroid_y) for cell in cells], dtype=float)
    cell_z_top_m = np.asarray(
        [
            np.nan if getattr(cell, "z_top_mean", None) is None else float(cell.z_top_mean)
            for cell in cells
        ],
        dtype=float,
    )
    cell_z_bottom_m = np.asarray(
        [
            np.nan if getattr(cell, "z_bottom_mean", None) is None else float(cell.z_bottom_mean)
            for cell in cells
        ],
        dtype=float,
    )
    cell_hydraulic_conductivity_m_s = np.asarray(
        [
            (
                np.nan
                if getattr(cell, "hydraulic_conductivity_m_s", None) is None
                else float(cell.hydraulic_conductivity_m_s)
            )
            for cell in cells
        ],
        dtype=float,
    )
    cell_storage_coefficient = np.asarray(
        [
            (
                np.nan
                if getattr(cell, "storage_coefficient", None) is None
                else float(cell.storage_coefficient)
            )
            for cell in cells
        ],
        dtype=float,
    )

    edge_ids: list[int] = []
    edge_node_a_index: list[int] = []
    edge_node_b_index: list[int] = []
    edge_cell_a: list[int] = []
    edge_cell_b: list[int] = []
    edge_midpoint_x_m: list[float] = []
    edge_midpoint_y_m: list[float] = []
    edge_kind: list[str] = []
    edge_is_river: list[bool] = []
    geology_a_key: list[str] = []
    geology_b_key: list[str] = []

    for edge in edges:
        node_a_index = int(node_index_by_id[int(edge.node_a)])
        node_b_index = int(node_index_by_id[int(edge.node_b)])
        cell_a_index = int(cell_index_by_id[int(edge.cell_a)])
        cell_b_index = -1
        if getattr(edge, "cell_b", None) is not None:
            cell_b_index = int(cell_index_by_id[int(edge.cell_b)])

        edge_ids.append(int(edge.edge_id))
        edge_node_a_index.append(node_a_index)
        edge_node_b_index.append(node_b_index)
        edge_cell_a.append(cell_a_index)
        edge_cell_b.append(cell_b_index)
        edge_midpoint_x_m.append(
            0.5 * (float(node_x_m[node_a_index]) + float(node_x_m[node_b_index]))
        )
        edge_midpoint_y_m.append(
            0.5 * (float(node_y_m[node_a_index]) + float(node_y_m[node_b_index]))
        )
        edge_kind.append(str(edge.edge_kind))
        edge_is_river.append(bool(edge.is_river))
        geology_a_key.append(str(edge.geology_a_key))
        geology_b_key.append(str(edge.geology_b_key))

    mesh_path = getattr(bundle, "mesh_path", None)
    bundle_dir = getattr(bundle, "bundle_dir", None)
    boundary_labels_by_edge_id = _infer_boundary_labels_by_edge_id(
        edge_ids=np.asarray(edge_ids, dtype=int),
        edge_cell_b=np.asarray(edge_cell_b, dtype=int),
        edge_midpoint_x_m=np.asarray(edge_midpoint_x_m, dtype=float),
        edge_midpoint_y_m=np.asarray(edge_midpoint_y_m, dtype=float),
        x_min_m=float(np.min(node_x_m)) if node_x_m.size > 0 else 0.0,
        x_max_m=float(np.max(node_x_m)) if node_x_m.size > 0 else 0.0,
        y_min_m=float(np.min(node_y_m)) if node_y_m.size > 0 else 0.0,
        y_max_m=float(np.max(node_y_m)) if node_y_m.size > 0 else 0.0,
    )
    return GmshSupportMetadata(
        mesh_path=None if mesh_path is None else Path(mesh_path),
        bundle_dir=None if bundle_dir is None else Path(bundle_dir),
        cell_ids=cell_ids,
        node_ids=node_ids,
        node_x_m=node_x_m,
        node_y_m=node_y_m,
        cell_node_indices=cell_node_indices,
        cell_centroid_x_m=cell_centroid_x_m,
        cell_centroid_y_m=cell_centroid_y_m,
        cell_z_top_m=cell_z_top_m,
        cell_z_bottom_m=cell_z_bottom_m,
        cell_hydraulic_conductivity_m_s=cell_hydraulic_conductivity_m_s,
        cell_storage_coefficient=cell_storage_coefficient,
        edge_ids=np.asarray(edge_ids, dtype=int),
        edge_node_a_index=np.asarray(edge_node_a_index, dtype=int),
        edge_node_b_index=np.asarray(edge_node_b_index, dtype=int),
        edge_cell_a=np.asarray(edge_cell_a, dtype=int),
        edge_cell_b=np.asarray(edge_cell_b, dtype=int),
        edge_midpoint_x_m=np.asarray(edge_midpoint_x_m, dtype=float),
        edge_midpoint_y_m=np.asarray(edge_midpoint_y_m, dtype=float),
        edge_kind=tuple(edge_kind),
        edge_is_river=np.asarray(edge_is_river, dtype=bool),
        geology_a_key=tuple(geology_a_key),
        geology_b_key=tuple(geology_b_key),
        boundary_labels_by_edge_id=boundary_labels_by_edge_id,
    )


def _river_face_mask(
    support: GmshSupportMetadata,
    *,
    vertices: np.ndarray,
    edge_node_a: np.ndarray,
    edge_node_b: np.ndarray,
) -> np.ndarray:
    """Flag the faces of another mesh that a river edge of ``support`` crosses."""
    river = np.flatnonzero(np.asarray(support.edge_is_river, dtype=bool).reshape(-1))
    mask = np.zeros(edge_node_a.size, dtype=bool)
    if river.size == 0 or edge_node_a.size == 0:
        return mask

    import shapely
    from shapely.strtree import STRtree

    node_x_m = np.asarray(support.node_x_m, dtype=float)
    node_y_m = np.asarray(support.node_y_m, dtype=float)
    river_a = np.asarray(support.edge_node_a_index, dtype=int)[river]
    river_b = np.asarray(support.edge_node_b_index, dtype=int)[river]
    river_lines = shapely.linestrings(
        np.stack(
            [
                np.column_stack([node_x_m[river_a], node_y_m[river_a]]),
                np.column_stack([node_x_m[river_b], node_y_m[river_b]]),
            ],
            axis=1,
        )
    )
    faces = shapely.linestrings(np.stack([vertices[edge_node_a], vertices[edge_node_b]], axis=1))
    hits = STRtree(faces).query(river_lines, predicate="intersects")
    mask[np.unique(hits[1])] = True
    return mask


def _cell_sizes_m(
    vertices: np.ndarray, cell_node_indices: tuple[tuple[int, ...], ...]
) -> np.ndarray:
    """Return the square root of each polygon area (shoelace)."""
    sizes = np.zeros(len(cell_node_indices), dtype=float)
    for cell_index, nodes in enumerate(cell_node_indices):
        xy = vertices[list(nodes)]
        area = 0.5 * abs(
            float(np.dot(xy[:, 0], np.roll(xy[:, 1], -1)))
            - float(np.dot(xy[:, 1], np.roll(xy[:, 0], -1)))
        )
        sizes[cell_index] = np.sqrt(area)
    return sizes


def _with_centred_side_cells(
    face_support: GmshSupportMetadata, *, cell_size_m: np.ndarray
) -> GmshSupportMetadata:
    """Give each outer side the cells whose centre lies on it.

    A Dirichlet head belongs on the boundary. A dual cell centred on a boundary
    node carries it there; a clipped interior cell that only touches the side
    would hold it up to half a cell inside. A corner cell belongs to both sides,
    as on the structured grid. A side with no centred cell keeps the cells with a
    face on it, with a warning.
    """
    center_x_m = np.asarray(face_support.cell_centroid_x_m, dtype=float)
    center_y_m = np.asarray(face_support.cell_centroid_y_m, dtype=float)
    tolerance_m = np.maximum(1.0e-9, 1.0e-6 * np.asarray(cell_size_m, dtype=float))
    offsets = {
        "west_side": center_x_m - face_support.x_min_m,
        "east_side": center_x_m - face_support.x_max_m,
        "south_side": center_y_m - face_support.y_min_m,
        "north_side": center_y_m - face_support.y_max_m,
    }
    side_cells: dict[str, np.ndarray] = {}
    for side in _SIDE_IDS:
        centred = np.flatnonzero(np.abs(offsets[side]) <= tolerance_m).astype(int)
        if centred.size > 0:
            side_cells[side] = centred
            continue
        touching = face_support.boundary_cell_indices_for_side(side)
        if touching.size > 0:
            logger.warning(
                "No cell of the solver mesh is centred on %s; the %d cells with a face "
                "on it carry it instead.",
                side,
                int(touching.size),
            )

    edge_ids = np.asarray(face_support.edge_ids, dtype=int)
    edge_cell_a = np.asarray(face_support.edge_cell_a, dtype=int)
    owner_by_edge_id = dict(zip(edge_ids.tolist(), edge_cell_a.tolist(), strict=True))
    cells_by_side = {side: set(cells.tolist()) for side, cells in side_cells.items()}
    # A side face keeps its label only when its cell carries the side.
    labels = {
        edge_id: label
        for edge_id, label in face_support.boundary_labels_by_edge_id.items()
        if label not in cells_by_side or owner_by_edge_id[edge_id] in cells_by_side[label]
    }
    return replace(face_support, side_cell_indices=side_cells, boundary_labels_by_edge_id=labels)


def support_on_planar_mesh(
    support: GmshSupportMetadata, planar_mesh: HydroMesh
) -> GmshSupportMetadata:
    """Rebuild one support on the cells of another planar mesh of the same domain.

    MODFLOW 6 solves on the Voronoi dual of the bundle triangles by default. A
    feature located on ``support`` then names a triangle, not a solver cell. The
    support returned here describes the cells of ``planar_mesh`` instead: its
    nodes, cells and faces; as river faces, the faces a river edge of ``support``
    crosses, so the river cells are the cells the river runs through; and as
    the cells of each outer side, the cells centred on it. Cell centres are the
    mesh cell centres (the Voronoi generators). The bundle cell properties do
    not carry over: they stay NaN.
    """
    vertices = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    cell_node_indices = tuple(
        tuple(int(index) for index in np.asarray(cell, dtype=int).reshape(-1))
        for cell in planar_mesh.flat_connectivity
    )
    n_cells = len(cell_node_indices)
    center_x_m, center_y_m = planar_mesh.cell_centroids()

    owners: dict[tuple[int, int], list[int]] = {}
    for cell_index, nodes in enumerate(cell_node_indices):
        arity = len(nodes)
        for position in range(arity):
            node_a = nodes[position]
            node_b = nodes[(position + 1) % arity]
            if node_a == node_b:
                # Two corners merged by the vertex rounding: no face.
                continue
            key = (node_a, node_b) if node_a < node_b else (node_b, node_a)
            owners.setdefault(key, []).append(cell_index)

    edge_node_a = np.asarray([key[0] for key in owners], dtype=int)
    edge_node_b = np.asarray([key[1] for key in owners], dtype=int)
    edge_cell_a = np.asarray([cells[0] for cells in owners.values()], dtype=int)
    edge_cell_b = np.asarray(
        [cells[1] if len(cells) > 1 else -1 for cells in owners.values()], dtype=int
    )
    edge_ids = np.arange(edge_node_a.size, dtype=int)
    edge_midpoint_x_m = 0.5 * (vertices[edge_node_a, 0] + vertices[edge_node_b, 0])
    edge_midpoint_y_m = 0.5 * (vertices[edge_node_a, 1] + vertices[edge_node_b, 1])
    edge_is_river = _river_face_mask(
        support,
        vertices=vertices,
        edge_node_a=edge_node_a,
        edge_node_b=edge_node_b,
    )
    no_value = np.full(n_cells, np.nan, dtype=float)
    face_support = GmshSupportMetadata(
        mesh_path=support.mesh_path,
        bundle_dir=support.bundle_dir,
        cell_ids=np.arange(n_cells, dtype=int),
        node_ids=np.arange(vertices.shape[0], dtype=int),
        node_x_m=vertices[:, 0].copy(),
        node_y_m=vertices[:, 1].copy(),
        cell_node_indices=cell_node_indices,
        cell_centroid_x_m=np.asarray(center_x_m, dtype=float).reshape(-1),
        cell_centroid_y_m=np.asarray(center_y_m, dtype=float).reshape(-1),
        cell_z_top_m=no_value.copy(),
        cell_z_bottom_m=no_value.copy(),
        cell_hydraulic_conductivity_m_s=no_value.copy(),
        cell_storage_coefficient=no_value.copy(),
        edge_ids=edge_ids,
        edge_node_a_index=edge_node_a,
        edge_node_b_index=edge_node_b,
        edge_cell_a=edge_cell_a,
        edge_cell_b=edge_cell_b,
        edge_midpoint_x_m=edge_midpoint_x_m,
        edge_midpoint_y_m=edge_midpoint_y_m,
        edge_kind=tuple("boundary" if cell_b < 0 else "internal" for cell_b in edge_cell_b),
        edge_is_river=edge_is_river,
        geology_a_key=("",) * int(edge_ids.size),
        geology_b_key=("",) * int(edge_ids.size),
        boundary_labels_by_edge_id=_infer_boundary_labels_by_edge_id(
            edge_ids=edge_ids,
            edge_cell_b=edge_cell_b,
            edge_midpoint_x_m=edge_midpoint_x_m,
            edge_midpoint_y_m=edge_midpoint_y_m,
            x_min_m=float(np.min(vertices[:, 0])),
            x_max_m=float(np.max(vertices[:, 0])),
            y_min_m=float(np.min(vertices[:, 1])),
            y_max_m=float(np.max(vertices[:, 1])),
        ),
    )
    return _with_centred_side_cells(
        face_support, cell_size_m=_cell_sizes_m(vertices, cell_node_indices)
    )


__all__ = [
    "GmshSupportMetadata",
    "build_gmsh_support_metadata",
    "support_on_planar_mesh",
]
