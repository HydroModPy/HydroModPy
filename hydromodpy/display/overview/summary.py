"""Compute aggregate metrics for the overview stats card."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.core.contracts.overview import DataOverviewState


@dataclass(frozen=True)
class OverviewSummary:
    """Aggregated metrics rendered on the stats card."""

    watershed_name: str
    catchment_area_km2: float | None
    outlet_xy: tuple[float, float] | None
    n_hydrometry: int
    n_piezometry: int
    n_intermittency: int
    n_water_quality: int
    n_streams: int
    date_start: str
    date_end: str


def compute_overview_summary(state: DataOverviewState) -> OverviewSummary:
    """Compute the summary metrics from ``state``."""
    ld = state.loaded_data
    dg = state.domain_geographic
    overview = state.cfg.overview

    name = ""
    if overview is not None and overview.name:
        name = overview.name
    elif state.workspace is not None and hasattr(state.workspace, "paths"):
        name = state.workspace.paths.catch_name

    outlet: tuple[float, float] | None = None
    if dg is not None and dg.x_outlet is not None and dg.y_outlet is not None:
        outlet = (float(dg.x_outlet), float(dg.y_outlet))

    return OverviewSummary(
        watershed_name=name,
        catchment_area_km2=(float(dg.catchment_area_km2) if dg is not None else None),
        outlet_xy=outlet,
        n_hydrometry=_count_points(ld.hydrometry),
        n_piezometry=_count_points(ld.piezometry),
        n_intermittency=_count_points(ld.intermittency),
        n_water_quality=_count_points(ld.water_quality),
        n_streams=_count_streams(ld.hydrography),
        date_start=str(overview.date_start) if overview and overview.date_start else "",
        date_end=str(overview.date_end) if overview and overview.date_end else "",
    )


def _count_points(lr) -> int:
    if lr is None:
        return 0
    return len(getattr(lr, "points", []) or [])


def _count_streams(hydro) -> int:
    if hydro is None:
        return 0
    streams_path = _hydrography_vector_path(hydro)
    if streams_path is None:
        return 0
    try:
        import geopandas as gpd

        gdf = gpd.read_file(streams_path)
        return len(gdf)
    except Exception:
        return 0


def _hydrography_vector_path(hydro) -> str | None:
    for record in getattr(hydro, "fields", None) or ():
        metadata = getattr(record, "metadata", None)
        if isinstance(metadata, dict):
            path = metadata.get("vector_path")
            if path not in (None, ""):
                return str(path)
    return None
