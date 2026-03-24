"""Low-level Gmsh Python API helpers for zone-conformal mesh generation.

This module groups every function that directly calls the ``gmsh`` API so that
the higher-level ``conformal.py`` stays readable and testable.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point

from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader import (
    GmshCellBlock,
    GmshMeshData,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    iter_line_parts,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementFamilySettings,
)

_GMSH_ALGORITHM_BY_NAME = {
    "meshadapt": 1,
    "automatic": 2,
    "delaunay": 5,
    "frontal": 6,
}
_PLANAR_GMSH_ELEMENT_TYPES = {
    2: ("triangle", 3),
    3: ("quadrilateral", 4),
}


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def configure_gmsh_terminal_output(gmsh) -> None:
    """Silence verbose Gmsh terminal traces unless explicitly requested."""
    verbose_env = str(os.environ.get("HYDROMODPY_GMSH_VERBOSE", "")).strip().lower()
    if verbose_env in {"1", "true", "yes", "on"}:
        return
    for option_name, option_value in (
        ("General.Terminal", 0.0),
        ("General.Verbosity", 0.0),
    ):
        try:
            gmsh.option.setNumber(option_name, option_value)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Point / line coordinate snapping
# ---------------------------------------------------------------------------

def rounded_coord(value: float, *, tolerance: float) -> float:
    """Snap one coordinate to the tolerance grid used for point deduplication."""
    if tolerance > 0.0:
        snapped = round(float(value) / tolerance) * tolerance
        return float(np.round(snapped, 12))
    return float(np.round(float(value), 12))


def point_key(x: float, y: float, *, tolerance: float) -> tuple[float, float]:
    """Return the deduplicated registry key used for OCC points."""
    return (
        rounded_coord(float(x), tolerance=tolerance),
        rounded_coord(float(y), tolerance=tolerance),
    )


def _segment_is_degenerate(
    key0: tuple[float, float],
    key1: tuple[float, float],
    *,
    tolerance: float,
) -> bool:
    if key0 == key1:
        return True
    dx = float(key1[0]) - float(key0[0])
    dy = float(key1[1]) - float(key0[1])
    distance_sq = (dx * dx) + (dy * dy)
    threshold = max(float(tolerance) * float(tolerance), 1.0e-18)
    return bool(distance_sq <= threshold)


# ---------------------------------------------------------------------------
# OCC ring / polyline helpers
# ---------------------------------------------------------------------------

def add_ring_loop(
    occ,
    ring_coords,
    *,
    point_registry: dict[tuple[float, float], int],
    line_registry: dict[tuple[tuple[float, float], tuple[float, float]], int],
    point_size: float,
    tolerance: float,
) -> tuple[int, list[int]]:
    """Create one OCC curve loop from a polygon ring.

    The point and line registries ensure neighboring faces reuse the exact same
    OCC entities instead of creating almost-identical duplicates.
    """
    coords = np.asarray(ring_coords, dtype=float)
    if coords.shape[0] < 4:
        raise ValueError("Linear rings must contain at least 4 coordinates")
    oriented_curve_tags: list[int] = []
    curve_tags_abs: list[int] = []
    for idx in range(coords.shape[0] - 1):
        x0, y0 = float(coords[idx, 0]), float(coords[idx, 1])
        x1, y1 = float(coords[idx + 1, 0]), float(coords[idx + 1, 1])
        key0 = point_key(x0, y0, tolerance=tolerance)
        key1 = point_key(x1, y1, tolerance=tolerance)
        if _segment_is_degenerate(key0, key1, tolerance=tolerance):
            continue
        point_tag_0 = point_registry.get(key0)
        if point_tag_0 is None:
            point_tag_0 = occ.addPoint(key0[0], key0[1], 0.0, point_size)
            point_registry[key0] = int(point_tag_0)
        point_tag_1 = point_registry.get(key1)
        if point_tag_1 is None:
            point_tag_1 = occ.addPoint(key1[0], key1[1], 0.0, point_size)
            point_registry[key1] = int(point_tag_1)
        if int(point_tag_0) == int(point_tag_1):
            continue

        canonical = (key0, key1) if key0 <= key1 else (key1, key0)
        line_tag = line_registry.get(canonical)
        if line_tag is None:
            line_tag = occ.addLine(point_tag_0, point_tag_1)
            line_registry[canonical] = int(line_tag)
            oriented_curve_tags.append(int(line_tag))
        else:
            oriented_curve_tags.append(
                int(line_tag) if canonical == (key0, key1) else -int(line_tag)
            )
        curve_tags_abs.append(abs(int(line_tag)))

    if not oriented_curve_tags:
        raise ValueError("Cannot build a Gmsh curve loop from a degenerate ring")
    return occ.addCurveLoop(oriented_curve_tags), curve_tags_abs


def add_polyline_segments(
    occ,
    line_coords,
    *,
    point_registry: dict[tuple[float, float], int],
    line_registry: dict[tuple[tuple[float, float], tuple[float, float]], int],
    point_size: float,
    tolerance: float,
) -> list[int]:
    """Create OCC line segments for one polyline while reusing shared entities."""
    coords = np.asarray(line_coords, dtype=float)
    if coords.shape[0] < 2:
        return []
    curve_tags_abs: list[int] = []
    for idx in range(coords.shape[0] - 1):
        x0, y0 = float(coords[idx, 0]), float(coords[idx, 1])
        x1, y1 = float(coords[idx + 1, 0]), float(coords[idx + 1, 1])
        key0 = point_key(x0, y0, tolerance=tolerance)
        key1 = point_key(x1, y1, tolerance=tolerance)
        if _segment_is_degenerate(key0, key1, tolerance=tolerance):
            continue
        point_tag_0 = point_registry.get(key0)
        if point_tag_0 is None:
            point_tag_0 = occ.addPoint(key0[0], key0[1], 0.0, point_size)
            point_registry[key0] = int(point_tag_0)
        point_tag_1 = point_registry.get(key1)
        if point_tag_1 is None:
            point_tag_1 = occ.addPoint(key1[0], key1[1], 0.0, point_size)
            point_registry[key1] = int(point_tag_1)
        if int(point_tag_0) == int(point_tag_1):
            continue

        canonical = (key0, key1) if key0 <= key1 else (key1, key0)
        line_tag = line_registry.get(canonical)
        if line_tag is None:
            line_tag = occ.addLine(point_tag_0, point_tag_1)
            line_registry[canonical] = int(line_tag)
        curve_tags_abs.append(abs(int(line_tag)))
    return curve_tags_abs


# ---------------------------------------------------------------------------
# River lines extraction
# ---------------------------------------------------------------------------

def iter_river_lines_from_trace(river_trace: object | None) -> list[LineString]:
    """Extract non-empty LineString geometries from one river trace payload."""
    if river_trace is None:
        return []
    lines_attr = getattr(river_trace, "lines", None)
    if lines_attr is None:
        raise TypeError("river_trace must expose a 'lines' attribute when provided")
    lines: list[LineString] = []
    for geometry in lines_attr:
        if isinstance(geometry, (LineString, MultiLineString)):
            lines.extend(
                line
                for line in iter_line_parts(geometry)
                if float(line.length) > 0.0
            )
            continue
        raise TypeError(
            "river_trace.lines must contain only LineString or MultiLineString geometries"
        )
    return lines


# ---------------------------------------------------------------------------
# Mesh options
# ---------------------------------------------------------------------------

def apply_mesh_options(
    gmsh,
    *,
    algorithm: str,
    global_size: float,
    min_size: float | None,
    max_size: float | None,
) -> None:
    """Apply the coarse global mesh-size policy and chosen 2D algorithm."""
    algorithm_key = str(algorithm).strip().lower()
    if algorithm_key not in _GMSH_ALGORITHM_BY_NAME:
        allowed = ", ".join(sorted(_GMSH_ALGORITHM_BY_NAME))
        raise ValueError(
            f"Unsupported Gmsh 2D algorithm '{algorithm}'. Allowed: {allowed}"
        )
    gmsh.option.setNumber(
        "Mesh.Algorithm", float(_GMSH_ALGORITHM_BY_NAME[algorithm_key])
    )
    gmsh.option.setNumber(
        "Mesh.MeshSizeMin", float(min_size if min_size is not None else global_size)
    )
    gmsh.option.setNumber(
        "Mesh.MeshSizeMax", float(max_size if max_size is not None else global_size)
    )


def _disable_automatic_mesh_size_sources(gmsh) -> None:
    """Force Gmsh to rely only on explicitly constructed background fields."""
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0.0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0.0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0.0)


def set_background_mesh_from_fields(
    gmsh,
    *,
    field_tags: list[int] | tuple[int, ...],
) -> int | None:
    """Activate one background mesh field, combining multiple fields with Min."""
    unique_tags = sorted(set(int(tag) for tag in field_tags if int(tag) > 0))
    if not unique_tags:
        return None

    field_api = gmsh.model.mesh.field
    if len(unique_tags) == 1:
        background_field = int(unique_tags[0])
    else:
        background_field = int(field_api.add("Min"))
        field_api.setNumbers(background_field, "FieldsList", unique_tags)
    field_api.setAsBackgroundMesh(background_field)
    _disable_automatic_mesh_size_sources(gmsh)
    return int(background_field)


# ---------------------------------------------------------------------------
# Physical group naming
# ---------------------------------------------------------------------------

def build_curve_group_name(
    zone_keys: set[str],
    *,
    is_boundary: bool = True,
) -> tuple[str, str, tuple[str, ...]]:
    """Return the exported physical-group name for one boundary/interface curve."""
    zone_names = tuple(sorted(str(zone_key) for zone_key in zone_keys))
    if len(zone_names) >= 2:
        return ("interface::" + "::".join(zone_names), "interface_curve", zone_names)
    if len(zone_names) == 1:
        if not bool(is_boundary):
            return (f"constraint::{zone_names[0]}", "constraint_curve", zone_names)
        return (f"boundary::{zone_names[0]}", "boundary_curve", zone_names)
    raise ValueError("curve groups require at least one owning zone")


# ---------------------------------------------------------------------------
# Interface refinement field
# ---------------------------------------------------------------------------

def apply_interface_refinement_field(
    gmsh,
    *,
    interface_curve_tags: list[int],
    global_size: float,
    refine_interfaces: bool,
    interface_size: float | None,
    interface_distance: float | None,
    interface_sampling: int,
    stop_at_distance_max: bool = False,
) -> dict[str, Any]:
    """Create the optional distance-based refinement field around interface curves."""
    summary: dict[str, Any] = {
        "enabled": bool(refine_interfaces),
        "interface_size": None if interface_size is None else float(interface_size),
        "interface_distance": (
            None if interface_distance is None else float(interface_distance)
        ),
        "interface_sampling": int(interface_sampling),
        "interface_curve_count": int(
            len(sorted(set(int(tag) for tag in interface_curve_tags)))
        ),
        "stop_at_distance_max": bool(stop_at_distance_max),
        "background_field": None,
    }
    if (not refine_interfaces) or (not interface_curve_tags):
        return summary
    if interface_size is None or interface_distance is None:
        raise ValueError(
            "interface_size and interface_distance are required when interface refinement is enabled."
        )

    field_api = gmsh.model.mesh.field
    unique_curves = sorted(set(int(tag) for tag in interface_curve_tags))

    distance_field = int(field_api.add("Distance"))
    field_api.setNumbers(distance_field, "CurvesList", unique_curves)
    field_api.setNumber(distance_field, "Sampling", float(interface_sampling))

    threshold_field = int(field_api.add("Threshold"))
    field_api.setNumber(threshold_field, "IField", float(distance_field))
    field_api.setNumber(threshold_field, "LcMin", float(interface_size))
    field_api.setNumber(threshold_field, "LcMax", float(global_size))
    field_api.setNumber(threshold_field, "DistMin", 0.0)
    field_api.setNumber(threshold_field, "DistMax", float(interface_distance))
    if stop_at_distance_max:
        field_api.setNumber(threshold_field, "StopAtDistMax", 1.0)

    background_field = int(field_api.add("Min"))
    field_api.setNumbers(background_field, "FieldsList", [threshold_field])
    field_api.setAsBackgroundMesh(background_field)
    _disable_automatic_mesh_size_sources(gmsh)

    summary["background_field"] = {
        "distance_field_tag": int(distance_field),
        "threshold_field_tag": int(threshold_field),
        "background_field_tag": int(background_field),
    }
    return summary


def apply_family_refinement_fields(
    gmsh,
    *,
    family_curve_tags: Mapping[str, list[int] | tuple[int, ...]],
    global_size: float,
    refine_interfaces: bool,
    family_settings: Mapping[str, ZoneMeshingRefinementFamilySettings],
    default_interface_size: float,
    default_interface_distance: float,
    default_interface_sampling: int,
    stop_at_distance_max: bool = False,
) -> dict[str, Any]:
    """Create one distance-based refinement field per interface family."""

    summary: dict[str, Any] = {
        "enabled": bool(refine_interfaces),
        "interface_curve_count": 0,
        "active_families": [],
        "stop_at_distance_max": bool(stop_at_distance_max),
        "family_fields": {},
        "background_field": None,
    }
    if not refine_interfaces:
        return summary

    field_api = gmsh.model.mesh.field
    threshold_fields: list[int] = []
    total_curve_count = 0
    active_families: list[str] = []

    for family_name, curve_tags in sorted(family_curve_tags.items()):
        unique_curves = sorted(set(int(tag) for tag in curve_tags))
        family_cfg = family_settings.get(str(family_name))
        if family_cfg is None or not family_cfg.enabled or not unique_curves:
            summary["family_fields"][str(family_name)] = {
                "enabled": False,
                "interface_curve_count": int(len(unique_curves)),
            }
            continue

        interface_size = float(
            default_interface_size
            if family_cfg.interface_size is None
            else family_cfg.interface_size
        )
        interface_distance = float(
            default_interface_distance
            if family_cfg.interface_distance is None
            else family_cfg.interface_distance
        )
        interface_sampling = int(
            default_interface_sampling
            if family_cfg.interface_sampling is None
            else family_cfg.interface_sampling
        )

        distance_field = int(field_api.add("Distance"))
        field_api.setNumbers(distance_field, "CurvesList", unique_curves)
        field_api.setNumber(distance_field, "Sampling", float(interface_sampling))

        threshold_field = int(field_api.add("Threshold"))
        field_api.setNumber(threshold_field, "IField", float(distance_field))
        field_api.setNumber(threshold_field, "LcMin", float(interface_size))
        field_api.setNumber(threshold_field, "LcMax", float(global_size))
        field_api.setNumber(threshold_field, "DistMin", 0.0)
        field_api.setNumber(threshold_field, "DistMax", float(interface_distance))
        if stop_at_distance_max:
            field_api.setNumber(threshold_field, "StopAtDistMax", 1.0)

        threshold_fields.append(int(threshold_field))
        total_curve_count += len(unique_curves)
        active_families.append(str(family_name))
        summary["family_fields"][str(family_name)] = {
            "enabled": True,
            "priority": int(family_cfg.priority),
            "interface_curve_count": int(len(unique_curves)),
            "interface_size": float(interface_size),
            "interface_distance": float(interface_distance),
            "interface_sampling": int(interface_sampling),
            "distance_field_tag": int(distance_field),
            "threshold_field_tag": int(threshold_field),
        }

    summary["interface_curve_count"] = int(total_curve_count)
    summary["active_families"] = list(active_families)
    if not threshold_fields:
        return summary

    if len(threshold_fields) == 1:
        background_field = int(threshold_fields[0])
    else:
        background_field = int(field_api.add("Min"))
        field_api.setNumbers(background_field, "FieldsList", threshold_fields)
    field_api.setAsBackgroundMesh(background_field)
    _disable_automatic_mesh_size_sources(gmsh)

    summary["background_field"] = {
        "background_field_tag": int(background_field),
        "threshold_fields": [int(tag) for tag in threshold_fields],
    }
    return summary


def create_regional_structured_size_field(
    gmsh,
    *,
    region_geometry,
    domain_bounds: tuple[float, float, float, float],
    inside_size: float,
    outside_size: float,
    transition_distance: float,
    grid_resolution: float,
    scratch_dir: str | os.PathLike[str],
    field_name: str,
) -> tuple[int, dict[str, Any], Path]:
    """Create one structured inside/outside background-size field."""
    minx, miny, maxx, maxy = [float(value) for value in domain_bounds]
    width = max(float(maxx - minx), 0.0)
    height = max(float(maxy - miny), 0.0)
    if grid_resolution <= 0.0:
        raise ValueError("grid_resolution must be > 0 for regional size fields")

    nx = max(int(np.ceil(width / float(grid_resolution))) + 1, 2)
    ny = max(int(np.ceil(height / float(grid_resolution))) + 1, 2)
    dx = float(width / float(nx - 1)) if nx > 1 else float(grid_resolution)
    dy = float(height / float(ny - 1)) if ny > 1 else float(grid_resolution)
    boundary = region_geometry.boundary

    rows: list[str] = []
    for ix in range(nx):
        x = float(minx + (float(ix) * dx))
        values: list[str] = []
        for iy in range(ny):
            y = float(miny + (float(iy) * dy))
            point = Point(x, y)
            if bool(region_geometry.covers(point)):
                value = float(inside_size)
            else:
                value = float(outside_size)
                if transition_distance > 0.0:
                    distance_to_boundary = float(boundary.distance(point))
                    if distance_to_boundary < float(transition_distance):
                        ratio = float(distance_to_boundary / float(transition_distance))
                        value = float(
                            inside_size
                            + (ratio * (outside_size - inside_size))
                        )
            values.append(f"{float(value):.12g}")
        rows.append(" ".join(values))

    fd, tmp_path = tempfile.mkstemp(
        prefix="gmsh_structured_size_",
        suffix=".txt",
        dir=str(Path(scratch_dir)),
    )
    os.close(fd)
    field_path = Path(tmp_path)
    payload_lines = [
        f"{float(minx):.12g} {float(miny):.12g} 0",
        f"{float(dx):.12g} {float(dy):.12g} 1",
        f"{int(nx)} {int(ny)} 1",
        *rows,
    ]
    field_path.write_text("\n".join(payload_lines) + "\n", encoding="utf-8")

    field_api = gmsh.model.mesh.field
    field_tag = int(field_api.add("Structured"))
    field_api.setString(field_tag, "FileName", str(field_path))
    field_api.setNumber(field_tag, "TextFormat", 1.0)
    field_api.setNumber(field_tag, "SetOutsideValue", 1.0)
    field_api.setNumber(field_tag, "OutsideValue", float(outside_size))

    summary = {
        "enabled": True,
        "name": str(field_name),
        "inside_size": float(inside_size),
        "outside_size": float(outside_size),
        "transition_distance": float(transition_distance),
        "grid_resolution": float(grid_resolution),
        "grid_shape": [int(nx), int(ny), 1],
        "grid_spacing": [float(dx), float(dy), 1.0],
        "field_tag": int(field_tag),
    }
    return int(field_tag), summary, field_path


def write_repository_compatible_mesh(gmsh, output_path: str | os.PathLike[str]) -> None:
    """Write one planar mesh in the ASCII MSH2 format expected by repo readers.

    Some test and review utilities still rely on the lightweight repository
    fallback reader when ``meshio`` is unavailable. Keeping the writer settings
    here centralizes that compatibility choice instead of duplicating it in the
    higher-level conformal mesher.
    """

    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.option.setNumber("Mesh.Binary", 0)
    gmsh.write(str(output_path))


def build_runtime_planar_mesh_from_gmsh(
    gmsh,
    *,
    source_path: str | os.PathLike[str] | None = None,
) -> GmshPlanarMesh2D:
    """Capture one normalized planar mesh directly from one live Gmsh session."""
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    node_tags_arr = np.asarray(node_tags, dtype=int).reshape(-1)
    coords_arr = np.asarray(coords, dtype=float).reshape(-1, 3)
    if node_tags_arr.size != coords_arr.shape[0]:
        raise ValueError(
            "Live Gmsh node coordinates are inconsistent with returned node tags."
        )

    coords_by_tag = {
        int(tag): (float(coord[0]), float(coord[1]))
        for tag, coord in zip(node_tags_arr, coords_arr, strict=False)
    }
    element_types, _element_tags, element_nodes = gmsh.model.mesh.getElements(dim=2)

    used_node_tags: list[int] = []
    cell_blocks: list[GmshCellBlock] = []
    cell_kinds: set[str] = set()
    for element_type, flat_nodes in zip(
        np.asarray(element_types, dtype=int).reshape(-1),
        tuple(element_nodes),
        strict=False,
    ):
        block_spec = _PLANAR_GMSH_ELEMENT_TYPES.get(int(element_type))
        if block_spec is None:
            continue
        cell_type, nodes_per_cell = block_spec
        flat_nodes_arr = np.asarray(flat_nodes, dtype=int).reshape(-1)
        if flat_nodes_arr.size == 0:
            continue
        if flat_nodes_arr.size % nodes_per_cell != 0:
            raise ValueError(
                f"Live Gmsh {cell_type} block does not contain a whole number of cells."
            )
        cell_node_tags = flat_nodes_arr.reshape(-1, nodes_per_cell)
        used_node_tags.extend(int(tag) for tag in cell_node_tags.reshape(-1))
        cell_blocks.append(
            GmshCellBlock(
                cell_type=cell_type,
                connectivity=cell_node_tags,
            )
        )
        cell_kinds.add(cell_type)

    if not cell_blocks:
        raise ValueError(
            "Live Gmsh model does not contain supported 2D triangle/quadrilateral elements."
        )
    if len(cell_kinds) > 1:
        present = ", ".join(sorted(cell_kinds))
        raise ValueError(
            "Mixed 2D cell types are not supported in one planar mesh. "
            f"Found: {present}."
        )

    ordered_node_tags = sorted(set(int(tag) for tag in used_node_tags))
    missing_node_tags = [tag for tag in ordered_node_tags if tag not in coords_by_tag]
    if missing_node_tags:
        preview = ", ".join(str(tag) for tag in missing_node_tags[:5])
        raise ValueError(
            "Live Gmsh node coordinates are missing for at least one planar cell "
            f"node tag ({preview})."
        )

    node_index_by_tag = {
        int(tag): idx for idx, tag in enumerate(ordered_node_tags)
    }
    points_xy = np.asarray(
        [coords_by_tag[int(tag)] for tag in ordered_node_tags],
        dtype=float,
    )
    normalized_blocks = tuple(
        GmshCellBlock(
            cell_type=block.cell_type,
            connectivity=np.asarray(
                [
                    [node_index_by_tag[int(tag)] for tag in row]
                    for row in np.asarray(block.connectivity, dtype=int)
                ],
                dtype=int,
            ),
        )
        for block in cell_blocks
    )
    mesh_data = GmshMeshData(
        points_xy=points_xy,
        cell_blocks=normalized_blocks,
        source_path=None if source_path is None else Path(source_path).resolve(),
    )
    return GmshPlanarMesh2D.from_mesh_data(mesh_data)


__all__ = [
    "add_polyline_segments",
    "add_ring_loop",
    "create_regional_structured_size_field",
    "build_runtime_planar_mesh_from_gmsh",
    "apply_family_refinement_fields",
    "apply_interface_refinement_field",
    "apply_mesh_options",
    "build_curve_group_name",
    "configure_gmsh_terminal_output",
    "iter_river_lines_from_trace",
    "set_background_mesh_from_fields",
    "write_repository_compatible_mesh",
]
