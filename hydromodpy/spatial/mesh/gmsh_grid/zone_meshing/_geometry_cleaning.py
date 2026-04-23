"""Compatibility facade for geometry-cleaning helpers.

The original implementation accumulated several distinct responsibilities in
one large module. The code now lives in smaller helpers:

- ``_geometry_contracts.py`` for local dataclasses
- ``_geometry_utils.py`` for validation and part iteration
- ``_polygon_cleaning.py`` for polygon cleaning and overlap resolution
- ``_partition_split.py`` for line-based repartitioning
- ``_linework_matching.py`` for segment/linework matching

This facade preserves historic imports used throughout the meshing package and
in tests.
"""

from __future__ import annotations

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._geometry_contracts import (
    CleanedZonePolygonRow,
    ZoneDomainCleaningDiagnostics,
    ZoneGeometry,
    ZoneGeometryGrouping,
    ZoneRowCleaningDiagnostics,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._geometry_utils import (
    as_metric_tolerance,
    is_invalid_nonempty_geometry,
    iter_line_parts,
    iter_polygon_parts,
    make_valid_geometry,
    make_valid_linework,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._linework_matching import (
    segment_intersects_refinement_scope,
    segment_matches_linework,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._partition_split import (
    split_partition_with_constraint_lines,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._polygon_cleaning import (
    clean_domain_geometry,
    clean_zone_rows,
    group_zone_geometries,
    intersection_area,
    resolve_zone_overlaps,
)

__all__ = [
    "CleanedZonePolygonRow",
    "ZoneDomainCleaningDiagnostics",
    "ZoneGeometry",
    "ZoneGeometryGrouping",
    "ZoneRowCleaningDiagnostics",
    "as_metric_tolerance",
    "clean_domain_geometry",
    "clean_zone_rows",
    "group_zone_geometries",
    "intersection_area",
    "is_invalid_nonempty_geometry",
    "iter_line_parts",
    "iter_polygon_parts",
    "make_valid_geometry",
    "make_valid_linework",
    "resolve_zone_overlaps",
    "segment_intersects_refinement_scope",
    "segment_matches_linework",
    "split_partition_with_constraint_lines",
]
