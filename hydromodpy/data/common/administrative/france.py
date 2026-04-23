"""French administrative subdivision (département) detection.

Uses a bundled GeoPackage (``departement.gpkg``) containing simplified
department polygons in EPSG:2154 (Lambert-93).  The file ships with the
package (~600 KB) so detection is purely local - no network call needed.

Source: IGN ADMIN EXPRESS COG CARTO (Licence Ouverte / ETALAB v2.0),
simplified to 500 m tolerance.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

_BUNDLED_GPKG = Path(__file__).parent / "departement.gpkg"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_departments_in_bbox(
    bbox: tuple[float, float, float, float],
) -> list[str]:
    """Return department codes whose territory intersects *bbox*.

    Parameters
    ----------
    bbox : (xmin, ymin, xmax, ymax) in **EPSG:2154** (Lambert-93).

    Returns
    -------
    Sorted list of 3-character zero-padded department codes
    (e.g. ``["022", "029", "035", "056"]``).
    """
    depts = gpd.read_file(str(_BUNDLED_GPKG))
    if depts.crs is not None and depts.crs.to_epsg() != 2154:
        depts = depts.to_crs("EPSG:2154")

    bbox_geom = box(*bbox)
    mask = depts.geometry.notna() & (~depts.geometry.is_empty)
    intersecting = depts.loc[mask & depts.geometry.intersects(bbox_geom)]

    code_col = _find_code_column(intersecting)
    raw_codes = [str(c).strip() for c in intersecting[code_col]]
    return sorted(_to_padded_codes(raw_codes))


def department_code_to_padded(dept_code: str) -> str:
    """Normalize a department code to 3-character zero-padded format.

    Examples: ``"35"`` becomes ``"035"``, ``"2A"`` becomes ``"02A"``,
    ``"971"`` stays ``"971"``.
    """
    code = str(dept_code).strip().upper()
    if code in ("2A", "2B"):
        return f"0{code}"
    if code in ("02A", "02B"):
        return code
    if code.isdigit():
        return code.zfill(3)
    return code


# Backward-compatible alias used by geology.
department_code_to_brgm_code = department_code_to_padded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_code_column(gdf: gpd.GeoDataFrame) -> str:
    """Find the column holding the department code (INSEE)."""
    for name in ("code_insee", "code", "code_dept", "CODE_DEPT", "INSEE_DEP"):
        if name in gdf.columns:
            return name
    raise ValueError(f"Cannot find department code column. Available: {list(gdf.columns)}")


def _to_padded_codes(raw_codes: Sequence[str] | set[str]) -> set[str]:
    """Normalize a list of raw department codes to 3-char zero-padded format."""
    return {department_code_to_padded(c) for c in raw_codes}
