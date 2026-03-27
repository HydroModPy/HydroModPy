"""Input normalization helpers for zone-conformal meshing.

The public meshing entry point accepts several optional payloads. These helpers
centralize their validation so the orchestration code can stay linear and easy
to read.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_utils import (
    iter_polygon_parts,
    make_valid_geometry,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._gmsh_driver import (
    iter_river_lines_from_trace,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.contracts import (
    ZoneLinearConstraint,
    ZoneRegionalSizeField,
)


def _constraint_sort_key(constraint: ZoneLinearConstraint) -> tuple[int, str]:
    """Sort constraints so river-like constraints win when a segment matches many."""
    token = str(constraint.kind).strip().lower()
    if token == "watershed_boundary":
        return (0, str(constraint.name))
    if token == "river_trace":
        return (1, str(constraint.name))
    return (10, str(constraint.name))


def normalize_linear_constraints(
    *,
    linear_constraints: Sequence[ZoneLinearConstraint] | None,
    river_trace: object | None,
) -> tuple[ZoneLinearConstraint, ...]:
    """Merge explicit linear constraints with the optional river trace payload."""
    if linear_constraints is not None:
        out = [constraint for constraint in linear_constraints]
        return tuple(sorted(out, key=_constraint_sort_key))

    river_lines = iter_river_lines_from_trace(river_trace)
    if not river_lines:
        return ()
    return (
        ZoneLinearConstraint(
            name="river::trace",
            kind="river_trace",
            lines=tuple(river_lines),
            participates_in_refinement=True,
        ),
    )


def normalize_regional_size_fields(
    *,
    regional_size_fields: Sequence[ZoneRegionalSizeField] | None,
    domain_geometry: BaseGeometry,
) -> tuple[ZoneRegionalSizeField, ...]:
    """Validate and clip optional regional size fields to the meshing domain."""
    if not regional_size_fields:
        return ()

    normalized: list[ZoneRegionalSizeField] = []
    for payload in regional_size_fields:
        name = str(payload.name).strip()
        if name == "":
            raise ValueError("regional size fields require one non-empty name")
        inside_size = float(payload.inside_size)
        outside_size = float(payload.outside_size)
        grid_resolution = float(payload.grid_resolution)
        transition_distance = (
            None
            if payload.transition_distance is None
            else float(payload.transition_distance)
        )
        if (not np.isfinite(inside_size)) or inside_size <= 0.0:
            raise ValueError(
                f"regional size field '{name}' requires inside_size > 0"
            )
        if (not np.isfinite(outside_size)) or outside_size <= 0.0:
            raise ValueError(
                f"regional size field '{name}' requires outside_size > 0"
            )
        if (not np.isfinite(grid_resolution)) or grid_resolution <= 0.0:
            raise ValueError(
                f"regional size field '{name}' requires grid_resolution > 0"
            )
        if transition_distance is not None and (
            (not np.isfinite(transition_distance)) or transition_distance < 0.0
        ):
            raise ValueError(
                f"regional size field '{name}' requires transition_distance >= 0"
            )

        clipped_geometry = make_valid_geometry(
            make_valid_geometry(payload.region_geometry).intersection(domain_geometry)
        )
        polygons = list(iter_polygon_parts(clipped_geometry))
        if not polygons:
            continue
        normalized.append(
            ZoneRegionalSizeField(
                name=name,
                region_geometry=make_valid_geometry(unary_union(polygons)),
                inside_size=inside_size,
                outside_size=outside_size,
                transition_distance=transition_distance,
                grid_resolution=grid_resolution,
            )
        )
    return tuple(normalized)


def normalize_interface_refinement_inputs(
    *,
    global_size: float,
    refine_interfaces: bool,
    interface_size: float | None,
    interface_distance: float | None,
    interface_sampling: int,
) -> tuple[bool, float | None, float | None]:
    """Validate interface-refinement scalars before any Gmsh work starts."""
    if interface_sampling < 2:
        raise ValueError("interface_sampling must be >= 2")

    refine_interfaces_value = bool(refine_interfaces)
    interface_size_value = None if interface_size is None else float(interface_size)
    interface_distance_value = (
        None if interface_distance is None else float(interface_distance)
    )
    if not refine_interfaces_value:
        return False, interface_size_value, interface_distance_value

    if (
        interface_size_value is None
        or (not np.isfinite(interface_size_value))
        or interface_size_value <= 0.0
    ):
        raise ValueError(
            "interface_size must be finite and > 0 when refine_interfaces=true"
        )
    if interface_size_value > float(global_size):
        raise ValueError(
            "interface_size must be <= global_size when refine_interfaces=true"
        )
    if (
        interface_distance_value is None
        or (not np.isfinite(interface_distance_value))
        or interface_distance_value <= 0.0
    ):
        raise ValueError(
            "interface_distance must be finite and > 0 when refine_interfaces=true"
        )
    return True, interface_size_value, interface_distance_value
