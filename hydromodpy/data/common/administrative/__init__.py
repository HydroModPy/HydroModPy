"""Administrative boundary detection - country-specific subdivision lookup.

Currently supported countries:

- **France** (``france`` module): départements métropolitains + outre-mer.
  Bundled GeoPackage (~600 KB), purely local intersection.

To add a new country, create a ``<country>.py`` module here exposing at
minimum a ``find_subdivisions_in_bbox()`` function following the same
signature as :func:`france.find_departments_in_bbox`.
"""

from hydromodpy.data.common.administrative.france import (
    bbox_for_departments,
    bbox_for_regions,
    department_code_to_padded,
    find_departments_in_bbox,
    find_departments_in_regions,
    french_region_code,
    known_french_region_names,
    normalize_french_region_key,
    validate_french_regions,
)

__all__ = (
    "bbox_for_departments",
    "bbox_for_regions",
    "department_code_to_padded",
    "find_departments_in_bbox",
    "find_departments_in_regions",
    "french_region_code",
    "known_french_region_names",
    "normalize_french_region_key",
    "validate_french_regions",
)
