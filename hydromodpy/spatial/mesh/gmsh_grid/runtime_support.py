"""Runtime support metadata paired with one loaded Gmsh planar mesh.

The planar mesh object stays responsible for geometry and connectivity.
This module carries only the lightweight support metadata that solver
adapters may need later for robust boundary-condition or forcing mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


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
        """Return unique owner cells touched by one side boundary."""
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


__all__ = [
    "GmshSupportMetadata",
    "build_gmsh_support_metadata",
]
