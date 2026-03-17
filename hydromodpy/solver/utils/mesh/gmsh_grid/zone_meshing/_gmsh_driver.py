"""Low-level Gmsh Python API helpers for zone-conformal mesh generation.

This module groups every function that directly calls the ``gmsh`` API so that
the higher-level ``conformal.py`` stays readable and testable.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
from shapely.geometry import LineString, MultiLineString

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    iter_line_parts,
)

_GMSH_ALGORITHM_BY_NAME = {
    "meshadapt": 1,
    "automatic": 2,
    "delaunay": 5,
    "frontal": 6,
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
    if tolerance > 0.0:
        snapped = round(float(value) / tolerance) * tolerance
        return float(np.round(snapped, 12))
    return float(np.round(float(value), 12))


def point_key(x: float, y: float, *, tolerance: float) -> tuple[float, float]:
    return (
        rounded_coord(float(x), tolerance=tolerance),
        rounded_coord(float(y), tolerance=tolerance),
    )


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
        if key0 == key1:
            continue
        point_tag_0 = point_registry.get(key0)
        if point_tag_0 is None:
            point_tag_0 = occ.addPoint(key0[0], key0[1], 0.0, point_size)
            point_registry[key0] = int(point_tag_0)
        point_tag_1 = point_registry.get(key1)
        if point_tag_1 is None:
            point_tag_1 = occ.addPoint(key1[0], key1[1], 0.0, point_size)
            point_registry[key1] = int(point_tag_1)

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
    coords = np.asarray(line_coords, dtype=float)
    if coords.shape[0] < 2:
        return []
    curve_tags_abs: list[int] = []
    for idx in range(coords.shape[0] - 1):
        x0, y0 = float(coords[idx, 0]), float(coords[idx, 1])
        x1, y1 = float(coords[idx + 1, 0]), float(coords[idx + 1, 1])
        key0 = point_key(x0, y0, tolerance=tolerance)
        key1 = point_key(x1, y1, tolerance=tolerance)
        if key0 == key1:
            continue
        point_tag_0 = point_registry.get(key0)
        if point_tag_0 is None:
            point_tag_0 = occ.addPoint(key0[0], key0[1], 0.0, point_size)
            point_registry[key0] = int(point_tag_0)
        point_tag_1 = point_registry.get(key1)
        if point_tag_1 is None:
            point_tag_1 = occ.addPoint(key1[0], key1[1], 0.0, point_size)
            point_registry[key1] = int(point_tag_1)

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


# ---------------------------------------------------------------------------
# Physical group naming
# ---------------------------------------------------------------------------

def build_curve_group_name(
    zone_keys: set[str],
    *,
    is_boundary: bool = True,
) -> tuple[str, str, tuple[str, ...]]:
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
) -> dict[str, Any]:
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

    background_field = int(field_api.add("Min"))
    field_api.setNumbers(background_field, "FieldsList", [threshold_field])
    field_api.setAsBackgroundMesh(background_field)

    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0.0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0.0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0.0)

    summary["background_field"] = {
        "distance_field_tag": int(distance_field),
        "threshold_field_tag": int(threshold_field),
        "background_field_tag": int(background_field),
    }
    return summary
