"""Public facade for the site-selection workflow.

Detailed processing primitives live in the phase-specific subpackages:
``candidates``, ``evaluation``, ``evidence``, ``hydrology`` and ``outputs``.
"""

from __future__ import annotations

from hydromodpy.schema.site_selection_manifest import (
    SITE_SELECTION_MANIFEST_NAME,
    load_selection_manifest,
    validate_selection_manifest,
    write_selection_manifest,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.outputs.manifest import build_selection_manifest
from hydromodpy.spatial.site_selection.pipelines.build import (
    SiteSelectionBuildResult,
    build_site_selection_from_dem_area_light,
    build_site_selection_from_generated_network,
    build_site_selection_from_point_records,
)

__all__ = [
    "SITE_SELECTION_MANIFEST_NAME",
    "SiteSelectionBuildResult",
    "SiteSelectionConfig",
    "build_selection_manifest",
    "build_site_selection_from_dem_area_light",
    "build_site_selection_from_generated_network",
    "build_site_selection_from_point_records",
    "load_selection_manifest",
    "validate_selection_manifest",
    "write_selection_manifest",
]
