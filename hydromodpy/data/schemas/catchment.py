"""Contract for catchment polygon payloads.

A catchment is represented by a :class:`geopandas.GeoDataFrame` with
geometry, CRS and area attributes. We validate:

- the object is a non-empty GeoDataFrame
- every geometry is a (Multi)Polygon
- the CRS is declared
- the reported area in square kilometres is positive
- an ``outlet`` column is present or can be derived
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hydromodpy.core.exceptions import DataContractViolation


@dataclass(frozen=True)
class CatchmentPolygonSchema:
    """Declarative constraints for a catchment polygon payload."""

    min_area_km2: float = 0.001
    max_area_km2: float = 1_000_000.0
    require_crs: bool = True
    require_outlet: bool = False


def validate_catchment(
    gdf: Any,
    contract: CatchmentPolygonSchema | None = None,
    *,
    context: str | None = None,
) -> Any:
    """Validate a catchment polygon payload."""
    contract = contract or CatchmentPolygonSchema()
    failures: list[str] = []

    if not hasattr(gdf, "geometry") or not hasattr(gdf, "crs"):
        raise DataContractViolation(
            f"Catchment payload is not a GeoDataFrame{f' ({context})' if context else ''}",
        )

    if len(gdf) == 0:
        failures.append("Catchment GeoDataFrame is empty.")

    crs = getattr(gdf, "crs", None)
    if contract.require_crs and (crs is None or str(crs) == ""):
        failures.append("Catchment has no CRS declared.")

    geoms = gdf.geometry
    for idx, geom in enumerate(geoms):
        if geom is None or geom.is_empty:
            failures.append(f"Row {idx}: empty geometry.")
            continue
        gtype = geom.geom_type
        if gtype not in ("Polygon", "MultiPolygon"):
            failures.append(f"Row {idx}: geometry type {gtype!r} not allowed.")

    if "area_km2" in gdf.columns:
        try:
            areas = [float(a) for a in gdf["area_km2"].tolist()]
        except (TypeError, ValueError):
            failures.append("Column 'area_km2' is not numeric.")
            areas = []
        for idx, area in enumerate(areas):
            if not (contract.min_area_km2 <= area <= contract.max_area_km2):
                failures.append(
                    f"Row {idx}: area {area} km² outside "
                    f"[{contract.min_area_km2}, {contract.max_area_km2}]."
                )

    if contract.require_outlet and "outlet" not in gdf.columns:
        failures.append("Column 'outlet' is missing.")

    if failures:
        raise DataContractViolation(
            f"Catchment contract violated{f' ({context})' if context else ''}",
            failures=failures,
        )
    return gdf
