"""Hold the runnable example for 2D zone-conformal meshing on real geology.

This package complements the baseline Gmsh examples with a case where the mesh
is adapted to polygon boundaries. It is meant for geometric QA and reference
workflows, not for the low-level meshing algorithms themselves.

The package-level API intentionally exposes only the runnable entry points.
Private helper modules such as ``case_config``, ``planning`` and ``plotting``
remain internal implementation details.
"""

from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.run_case_zone_conformal import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_SECTION,
    main,
    run_reference_2d_zone_conformal_case_from_toml,
)

__all__ = [
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECTION",
    "main",
    "run_reference_2d_zone_conformal_case_from_toml",
]
