"""What the overview reads off the loaded data: stats card, stations, outlet, titles.

The panels (``report.py``) and the web page (``web.py``) draw from the same
readings here, so a station or a title is worked out once.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    elif getattr(state.cfg, "site", None) is not None:
        name = state.cfg.site.label or state.cfg.site.name

    return OverviewSummary(
        watershed_name=name,
        catchment_area_km2=(float(dg.catchment_area_km2) if dg is not None else None),
        outlet_xy=outlet_xy(dg),
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
    streams_path = hydrography_vector_path(hydro)
    if streams_path is None:
        return 0
    try:
        import geopandas as gpd

        gdf = gpd.read_file(streams_path)
        return len(gdf)
    except Exception:
        return 0


def hydrography_vector_path(hydro) -> str | None:
    """Return the vector file of the first hydrography record that names one."""
    for record in getattr(hydro, "fields", None) or ():
        metadata = getattr(record, "metadata", None)
        if isinstance(metadata, dict):
            path = metadata.get("vector_path")
            if path not in (None, ""):
                return str(path)
    return None


def outlet_xy(dg) -> tuple[float, float] | None:
    """Return the outlet of the domain as ``(x, y)``, or None when it has none."""
    if dg is not None and dg.x_outlet is not None and dg.y_outlet is not None:
        return (float(dg.x_outlet), float(dg.y_outlet))
    return None


def regional_context_title(label: str | None, candidates: Iterable[object]) -> str:
    """Name the regional map: the configured label, else a region read in a DEM name."""
    if label:
        return str(label)
    for candidate in candidates:
        if not candidate:
            continue
        name = Path(candidate).stem.lower()
        if "armorican" in name or "armoricain" in name:
            return "Setting in the Armorican Massif"
        if "bretagne" in name or "brittany" in name:
            return "Setting in Brittany"
    return "Regional setting"


_STATION_FAMILIES = (
    ("Hydrometry", "hydrometry"),
    ("Piezometry", "piezometry"),
    ("Intermittency", "intermittency"),
    ("Water quality", "water_quality"),
)


def station_inventory(state: DataOverviewState) -> list[dict[str, Any]]:
    """List every loaded station once: type, id, x, y, start and end dates.

    Stations are deduped by ``(type, station_id)`` so that variables like
    water_quality, which emit one record per (station, parameter), do not blow
    up the inventory into thousands of rows. The period is the union of the
    periods of all records of a station. ``x`` and ``y`` are None for a
    station without a location.
    """
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for label, attr in _STATION_FAMILIES:
        load_result = getattr(state.loaded_data, attr, None)
        for record in getattr(load_result, "points", ()) or ():
            station_id = str(getattr(record, "station_id", ""))
            loc = getattr(record, "location", None)
            start = _date_text(getattr(record, "date_start", None))
            end = _date_text(getattr(record, "date_end", None))
            key = (label, station_id)
            if key not in seen:
                seen[key] = {
                    "type": label,
                    "id": station_id,
                    "x": getattr(loc, "x", None),
                    "y": getattr(loc, "y", None),
                    "start": start,
                    "end": end,
                }
                continue
            row = seen[key]
            if start and (not row["start"] or start < row["start"]):
                row["start"] = start
            if end and (not row["end"] or end > row["end"]):
                row["end"] = end
    return list(seen.values())


def _date_text(value: Any) -> str:
    """Return the calendar day of a timestamp as text, or "" without one."""
    if value is None:
        return ""
    if hasattr(value, "date"):
        return str(value.date())
    return str(value)
