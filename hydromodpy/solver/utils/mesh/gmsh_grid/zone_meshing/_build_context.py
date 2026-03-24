"""Internal mutable build context for zone-conformal meshing.

The public entry point in ``conformal.py`` progressively accumulates geometry
registries, physical groups, refinement summaries and temporary files.  This
module centralizes that mutable state so the orchestration code can read more
like a pipeline and less like a long list of local dictionaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry


@dataclass
class ZoneMeshingBuildState:
    """Mutable registries carried across one meshing run."""

    point_registry: dict[tuple[float, float], int]
    line_registry: dict[tuple[tuple[float, float], tuple[float, float]], int]
    curve_usage: dict[int, set[str]]
    surface_tags_by_zone: dict[str, list[int]]
    surface_polygon_by_tag: dict[int, Polygon]
    physical_groups: list[Any]
    curve_tags_by_name: dict[str, list[int]]
    constraint_linework_by_name: dict[str, BaseGeometry]
    constraint_curve_tags_raw: dict[str, list[int]]
    constraint_embed_success_by_name: dict[str, int]
    constraint_embed_failures_by_name: dict[str, int]
    refinement_policy_summary: dict[str, Any] | None
    regional_background_summary: dict[str, Any] | None
    regional_field_temp_paths: list[Path]


def initialize_build_state(
    *,
    zone_keys: Sequence[str],
    constraint_names: Sequence[str],
) -> ZoneMeshingBuildState:
    """Create the mutable state container used during one meshing run."""
    return ZoneMeshingBuildState(
        point_registry={},
        line_registry={},
        curve_usage={},
        surface_tags_by_zone={str(zone_key): [] for zone_key in zone_keys},
        surface_polygon_by_tag={},
        physical_groups=[],
        curve_tags_by_name={},
        constraint_linework_by_name={},
        constraint_curve_tags_raw={
            str(constraint_name): [] for constraint_name in constraint_names
        },
        constraint_embed_success_by_name={
            str(constraint_name): 0 for constraint_name in constraint_names
        },
        constraint_embed_failures_by_name={
            str(constraint_name): 0 for constraint_name in constraint_names
        },
        refinement_policy_summary=None,
        regional_background_summary=None,
        regional_field_temp_paths=[],
    )


def compute_effective_max_size(
    *,
    global_size_value: float,
    max_size: float | None,
    prepared_regional_size_fields: Sequence[Any],
) -> float:
    """Return the practical upper mesh size once regional fields are considered."""
    effective_max_size = global_size_value if max_size is None else float(max_size)
    if prepared_regional_size_fields:
        effective_max_size = max(
            float(effective_max_size),
            max(
                max(float(field.inside_size), float(field.outside_size))
                for field in prepared_regional_size_fields
            ),
        )
    return float(effective_max_size)
