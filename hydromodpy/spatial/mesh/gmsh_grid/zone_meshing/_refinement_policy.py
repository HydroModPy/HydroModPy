"""Compatibility facade for local hotspot-aware refinement filtering.

The implementation is now split into narrower internal modules:

* ``_refinement_contracts.py`` for the shared dataclasses
* ``_refinement_candidates.py`` for candidate construction
* ``_refinement_hotspots.py`` for pairwise and grid hotspot detection
* ``_refinement_resolution.py`` for family-priority demotion and result assembly

This module intentionally keeps the historical import surface stable for
``conformal.py`` and for the existing tests.
"""

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_candidates import (
    build_refinement_candidates,
    refinement_family_from_group_name,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_contracts import (
    RefinementCurveCandidate,
    RefinementHotspot,
    RefinementPolicyResult,
    RefinementResolutionAction,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_hotspots import (
    detect_refinement_hotspots,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_resolution import (
    apply_local_refinement_policy,
)

__all__ = [
    "RefinementCurveCandidate",
    "RefinementHotspot",
    "RefinementPolicyResult",
    "RefinementResolutionAction",
    "apply_local_refinement_policy",
    "build_refinement_candidates",
    "detect_refinement_hotspots",
    "refinement_family_from_group_name",
]
