"""Background-field helpers for Gmsh-based zone meshing."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import Point

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementFamilySettings,
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
        "interface_distance": (None if interface_distance is None else float(interface_distance)),
        "interface_sampling": int(interface_sampling),
        "interface_curve_count": int(len(sorted(set(int(tag) for tag in interface_curve_tags)))),
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
                        value = float(inside_size + (ratio * (outside_size - inside_size)))
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


__all__ = [
    "apply_family_refinement_fields",
    "apply_interface_refinement_field",
    "create_regional_structured_size_field",
    "set_background_mesh_from_fields",
]
