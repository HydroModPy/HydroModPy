"""Low-level OCC helpers and shared Gmsh primitives for zone meshing."""

from __future__ import annotations

import os

import numpy as np
from shapely.geometry import LineString, MultiLineString

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._geometry_utils import (
    iter_line_parts,
)

_GMSH_ALGORITHM_BY_NAME = {
    "meshadapt": 1,
    "automatic": 2,
    "delaunay": 5,
    "frontal": 6,
}


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


def add_ring_loop(
    occ,
    ring_coords,
    *,
    point_registry: dict[tuple[float, float], int],
    line_registry: dict[tuple[tuple[float, float], tuple[float, float]], int],
    point_size: float,
    tolerance: float,
) -> tuple[int, list[int]]:
    """Create one OCC curve loop from a polygon ring."""
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
            lines.extend(line for line in iter_line_parts(geometry) if float(line.length) > 0.0)
            continue
        raise TypeError(
            "river_trace.lines must contain only LineString or MultiLineString geometries"
        )
    return lines


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
        raise ValueError(f"Unsupported Gmsh 2D algorithm '{algorithm}'. Allowed: {allowed}")
    gmsh.option.setNumber("Mesh.Algorithm", float(_GMSH_ALGORITHM_BY_NAME[algorithm_key]))
    gmsh.option.setNumber(
        "Mesh.MeshSizeMin", float(min_size if min_size is not None else global_size)
    )
    gmsh.option.setNumber(
        "Mesh.MeshSizeMax", float(max_size if max_size is not None else global_size)
    )


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


__all__ = [
    "add_polyline_segments",
    "add_ring_loop",
    "apply_mesh_options",
    "build_curve_group_name",
    "configure_gmsh_terminal_output",
    "iter_river_lines_from_trace",
]
