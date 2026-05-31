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

from hydromodpy.core.administrative_france import (
    french_region_code,
    known_french_region_names,
    normalize_french_region_key,
    validate_french_regions,
)

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
    depts = _read_departments_2154()

    bbox_geom = box(*bbox)
    mask = depts.geometry.notna() & (~depts.geometry.is_empty)
    intersecting = depts.loc[mask & depts.geometry.intersects(bbox_geom)]

    code_col = _find_code_column(intersecting)
    raw_codes = [str(c).strip() for c in intersecting[code_col]]
    return sorted(_to_padded_codes(raw_codes))


def find_departments_in_regions(regions: Sequence[str]) -> list[str]:
    """Return department codes for French administrative regions.

    Region names are matched after accent/case normalization, so both
    ``"Bretagne"`` and ``"Auvergne-Rhone-Alpes"`` are accepted. Direct region
    codes such as ``"53"`` are accepted as well.
    """

    region_codes = {french_region_code(region) for region in regions}
    depts = _read_departments_2154()
    if "code_insee_de_la_region" not in depts.columns:
        raise ValueError("Cannot find region code column in bundled department GeoPackage.")
    selected = depts.loc[
        depts["code_insee_de_la_region"].astype(str).str.strip().isin(region_codes)
    ]
    if selected.empty:
        raise ValueError(f"No French department found for regions: {list(regions)}")
    code_col = _find_code_column(selected)
    return sorted(_to_padded_codes(str(code) for code in selected[code_col]))


def bbox_for_departments(
    departments: Sequence[str],
    *,
    margin_m: float = 0.0,
) -> tuple[float, float, float, float]:
    """Return the EPSG:2154 bounding box covering the requested departments."""

    requested = {department_code_to_padded(dept) for dept in departments}
    depts = _read_departments_2154()
    code_col = _find_code_column(depts)
    codes = depts[code_col].astype(str).map(department_code_to_padded)
    selected = depts.loc[codes.isin(requested)]
    if selected.empty:
        raise ValueError(f"No French department found for codes: {list(departments)}")
    return _expand_bounds(tuple(float(v) for v in selected.total_bounds), margin_m)


def bbox_for_regions(
    regions: Sequence[str],
    *,
    margin_m: float = 0.0,
) -> tuple[float, float, float, float]:
    """Return the EPSG:2154 bounding box covering the requested regions."""

    departments = find_departments_in_regions(regions)
    return bbox_for_departments(departments, margin_m=margin_m)


def geometry_for_departments(
    departments: Sequence[str],
    *,
    target_crs: str | None = "EPSG:2154",
) -> object:
    """Return the union geometry covering the requested departments."""

    requested = {department_code_to_padded(dept) for dept in departments}
    depts = _read_departments_2154()
    code_col = _find_code_column(depts)
    codes = depts[code_col].astype(str).map(department_code_to_padded)
    selected = depts.loc[codes.isin(requested)]
    if selected.empty:
        raise ValueError(f"No French department found for codes: {list(departments)}")
    if target_crs and selected.crs is not None and str(selected.crs) != str(target_crs):
        selected = selected.to_crs(target_crs)
    return _union_geometry(selected)


def geometry_for_regions(
    regions: Sequence[str],
    *,
    target_crs: str | None = "EPSG:2154",
) -> object:
    """Return the union geometry covering the requested French regions."""

    departments = find_departments_in_regions(regions)
    return geometry_for_departments(departments, target_crs=target_crs)


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_departments_2154() -> gpd.GeoDataFrame:
    depts = gpd.read_file(str(_BUNDLED_GPKG))
    if depts.crs is not None and depts.crs.to_epsg() != 2154:
        depts = depts.to_crs("EPSG:2154")
    return depts


def _expand_bounds(
    bbox: tuple[float, float, float, float],
    margin_m: float,
) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = bbox
    margin = float(margin_m)
    if margin <= 0:
        return bbox
    return (xmin - margin, ymin - margin, xmax + margin, ymax + margin)


def _find_code_column(gdf: gpd.GeoDataFrame) -> str:
    """Find the column holding the department code (INSEE)."""
    for name in ("code_insee", "code", "code_dept", "CODE_DEPT", "INSEE_DEP"):
        if name in gdf.columns:
            return name
    raise ValueError(f"Cannot find department code column. Available: {list(gdf.columns)}")


def _to_padded_codes(raw_codes: Sequence[str] | set[str]) -> set[str]:
    """Normalize a list of raw department codes to 3-char zero-padded format."""
    return {department_code_to_padded(c) for c in raw_codes}


def _union_geometry(gdf: gpd.GeoDataFrame) -> object:
    geometries = gdf.geometry[gdf.geometry.notna() & (~gdf.geometry.is_empty)]
    if hasattr(geometries, "union_all"):
        return geometries.union_all()
    return geometries.unary_union


__all__ = [
    "bbox_for_departments",
    "bbox_for_regions",
    "department_code_to_padded",
    "find_departments_in_bbox",
    "find_departments_in_regions",
    "french_region_code",
    "geometry_for_departments",
    "geometry_for_regions",
    "known_french_region_names",
    "normalize_french_region_key",
    "validate_french_regions",
]
