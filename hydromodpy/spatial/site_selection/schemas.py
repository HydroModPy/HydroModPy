"""Stable schemas and row builders for site-selection outputs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from hydromodpy.spatial.site_selection.delineation import DelineatedCatchment

SELECTED_SITES_FIELDS = [
    "site_id",
    "site_label",
    "region_id",
    "source_selection_id",
    "site_status",
    "maturity",
    "x",
    "y",
    "x_outlet",
    "y_outlet",
    "area_km2",
    "tags",
    "enabled",
]
REGIONAL_LAB_SITES_FIELDS = SELECTED_SITES_FIELDS
SELECTED_SITES_SCHEMA = {
    "site_id": "Stable selected basin identifier.",
    "site_label": "Human-readable label; defaults to site_id.",
    "region_id": "Optional campaign or administrative region identifier.",
    "source_selection_id": "Selection campaign that produced the row.",
    "site_status": "Selection status, usually selected.",
    "maturity": "Downstream maturity flag, for example screening.",
    "x": "Outlet x coordinate in the outlet CRS.",
    "y": "Outlet y coordinate in the outlet CRS.",
    "x_outlet": "Explicit outlet x coordinate in the outlet CRS.",
    "y_outlet": "Explicit outlet y coordinate in the outlet CRS.",
    "area_km2": "Delineated catchment area in square kilometres when available.",
    "tags": "Semicolon-separated provenance tags.",
    "enabled": "Boolean flag used by downstream catalog loaders.",
}


def site_record_from_catchment(
    catchment: DelineatedCatchment,
    *,
    selection_id: str,
    region_id: str = "",
    site_status: str = "selected",
    maturity: str = "screening",
    extra_tags: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a flat selected-sites row from one catchment."""

    tags = ["site_selection", selection_id, *list(extra_tags)]
    return {
        "site_id": catchment.site_id,
        "site_label": catchment.site_id,
        "region_id": region_id,
        "source_selection_id": selection_id,
        "site_status": site_status,
        "maturity": maturity,
        "x": catchment.outlet.x,
        "y": catchment.outlet.y,
        "x_outlet": catchment.outlet.x,
        "y_outlet": catchment.outlet.y,
        "area_km2": "" if catchment.area_km2 is None else catchment.area_km2,
        "tags": ";".join(tags),
        "enabled": True,
    }


__all__ = [
    "REGIONAL_LAB_SITES_FIELDS",
    "SELECTED_SITES_FIELDS",
    "SELECTED_SITES_SCHEMA",
    "site_record_from_catchment",
]
