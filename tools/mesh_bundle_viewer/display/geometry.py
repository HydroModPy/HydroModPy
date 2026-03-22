"""Geometry preparation helpers for the standalone mesh visualization package."""

from __future__ import annotations

from collections.abc import Mapping

from ..bundle_contracts import MeshBundleLike


def build_node_xy_map(mesh: MeshBundleLike) -> dict[int, tuple[float, float]]:
    """Build a fast ``node_id -> (x, y)`` lookup for plotting."""

    return {int(node.node_id): (float(node.x), float(node.y)) for node in mesh.nodes}


def build_cell_polygons(
    mesh: MeshBundleLike,
    *,
    node_xy_map: Mapping[int, tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    """Translate cell connectivity into matplotlib-ready polygons."""

    polygons: list[list[tuple[float, float]]] = []
    for cell in mesh.cells:
        polygons.append([node_xy_map[int(node_id)] for node_id in cell.node_indices])
    return polygons


def build_triangulation_inputs(
    mesh: MeshBundleLike,
) -> tuple[list[float], list[float], list[tuple[int, int, int]]]:
    """Build node arrays and triangles used by continuous topography rendering."""

    local_index = {int(node.node_id): index for index, node in enumerate(mesh.nodes)}
    x_values = [float(node.x) for node in mesh.nodes]
    y_values = [float(node.y) for node in mesh.nodes]
    triangles: list[tuple[int, int, int]] = []

    for cell in mesh.cells:
        node_indices = [local_index[int(node_id)] for node_id in cell.node_indices]
        if len(node_indices) < 3:
            continue
        anchor = node_indices[0]
        for index in range(1, len(node_indices) - 1):
            triangles.append(
                (
                    int(anchor),
                    int(node_indices[index]),
                    int(node_indices[index + 1]),
                )
            )

    return x_values, y_values, triangles


def get_node_topography_values(
    mesh: MeshBundleLike,
) -> tuple[list[float], list[bool]]:
    """Return nodal top elevations plus a validity mask."""

    values: list[float] = []
    valid_mask: list[bool] = []

    for node in mesh.nodes:
        if node.z_top is None:
            values.append(0.0)
            valid_mask.append(False)
            continue
        values.append(float(node.z_top))
        valid_mask.append(True)

    return values, valid_mask


def has_continuous_node_topography(mesh: MeshBundleLike) -> bool:
    """Tell whether the bundle supports continuous nodal topography rendering."""

    _, valid_mask = get_node_topography_values(mesh)
    _, _, triangles = build_triangulation_inputs(mesh)
    return any(
        bool(valid_mask[i0] and valid_mask[i1] and valid_mask[i2])
        for i0, i1, i2 in triangles
    )


def get_numeric_cell_values(mesh: MeshBundleLike, field_name: str) -> list[float]:
    """Extract one numeric cell field for panel rendering."""

    values: list[float] = []
    for cell in mesh.cells:
        raw_value = getattr(cell, field_name, None)
        if raw_value is None:
            values.append(float("nan"))
            continue
        values.append(float(raw_value))
    return values


def get_categorical_cell_values(mesh: MeshBundleLike, field_name: str) -> list[str]:
    """Extract one categorical cell field for panel rendering."""

    values: list[str] = []
    for cell in mesh.cells:
        raw_value = getattr(cell, field_name)
        if raw_value is None or str(raw_value).strip() == "":
            values.append("non_renseigne")
            continue
        values.append(str(raw_value))
    return values


def build_edge_segments(
    mesh: MeshBundleLike,
    *,
    node_xy_map: Mapping[int, tuple[float, float]],
    selector,
) -> list[list[tuple[float, float]]]:
    """Build 2D edge segments matching the provided selector."""

    segments: list[list[tuple[float, float]]] = []
    for edge in mesh.edges:
        if not selector(edge):
            continue
        segments.append(
            [
                node_xy_map[int(edge.node_a)],
                node_xy_map[int(edge.node_b)],
            ]
        )
    return segments


def format_axes(ax, *, node_xy_map: Mapping[int, tuple[float, float]]) -> None:
    """Apply the common domain extent and axes formatting to one panel."""

    x_values = [coords[0] for coords in node_xy_map.values()]
    y_values = [coords[1] for coords in node_xy_map.values()]
    xmin = min(x_values)
    xmax = max(x_values)
    ymin = min(y_values)
    ymax = max(y_values)
    x_margin = 0.03 * max(xmax - xmin, 1.0)
    y_margin = 0.03 * max(ymax - ymin, 1.0)

    ax.set_xlim(xmin - x_margin, xmax + x_margin)
    ax.set_ylim(ymin - y_margin, ymax + y_margin)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")


def build_info_text(mesh: MeshBundleLike) -> str:
    """Build the small informational cartouche shown on the main panel."""

    metadata = dict(mesh.metadata)
    lines = [
        f"cellules : {mesh.n_cells}",
        f"noeuds : {mesh.n_nodes}",
        f"aretes : {mesh.n_edges}",
    ]
    crs = metadata.get("crs")
    if crs is not None:
        lines.append(f"crs : {crs}")
    constraints_mode = metadata.get("constraints_mode")
    if constraints_mode is not None:
        lines.append(f"mode : {constraints_mode}")
    geology_available = bool(metadata.get("geology", {}).get("available", False))
    lines.append(f"geologie : {'oui' if geology_available else 'non'}")
    return "\n".join(lines)


__all__ = [
    "build_cell_polygons",
    "build_edge_segments",
    "build_info_text",
    "build_node_xy_map",
    "build_triangulation_inputs",
    "format_axes",
    "get_categorical_cell_values",
    "get_node_topography_values",
    "get_numeric_cell_values",
    "has_continuous_node_topography",
]

