"""Legacy geographic compatibility helpers.

This package isolates the compatibility-oriented implementation that still
feeds the historical ``hydromodpy.geographic.Geographic`` facade.
"""

from hydromodpy.geographic.legacy.dem_metadata import (
    LegacyDemMetadata,
    read_legacy_dem_metadata,
)
from hydromodpy.geographic.legacy.domain_rasters import (
    LegacyDomainRasterProducts,
    build_legacy_domain_rasters,
)
from hydromodpy.geographic.legacy.pipeline import (
    LegacyGeographicContext,
    build_legacy_geographic_context,
)

__all__ = [
    "LegacyDemMetadata",
    "read_legacy_dem_metadata",
    "LegacyDomainRasterProducts",
    "build_legacy_domain_rasters",
    "LegacyGeographicContext",
    "build_legacy_geographic_context",
]
