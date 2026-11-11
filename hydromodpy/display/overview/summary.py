"""What the panels read: stats card, station table, outlet, titles.

The counts come from the rows of the data inventory, the same rows the seal
writes to ``data_inventory.parquet``, so the card and the page cannot differ.
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


def compute_overview_summary(
    state: DataOverviewState, inventory: list[dict[str, Any]]
) -> OverviewSummary:
    """Compute the summary metrics from ``state`` and the rows of the inventory."""
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
        n_hydrometry=_station_count(inventory, "hydrometry"),
        n_piezometry=_station_count(inventory, "piezometry"),
        n_intermittency=_station_count(inventory, "intermittency"),
        n_water_quality=_station_count(inventory, "water_quality"),
        n_streams=_count_streams(ld.hydrography),
        date_start=str(overview.date_start) if overview and overview.date_start else "",
        date_end=str(overview.date_end) if overview and overview.date_end else "",
    )


def _station_count(inventory: list[dict[str, Any]], family: str) -> int:
    return sum(1 for row in inventory if row["row_kind"] == "station" and row["family"] == family)


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


_STATION_LABELS = {
    "hydrometry": "Hydrometry",
    "piezometry": "Piezometry",
    "intermittency": "Intermittency",
    "water_quality": "Water quality",
}


def station_table(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """List the station rows of the inventory for the station panel.

    Each entry has the type label, id, x, y, and the first and last day as
    text. ``x`` and ``y`` are None for a station without a location.
    """
    return [
        {
            "type": _STATION_LABELS.get(row["family"], row["family"]),
            "id": row["item_id"],
            "x": row["x"],
            "y": row["y"],
            "start": _date_text(row["first"]),
            "end": _date_text(row["last"]),
        }
        for row in inventory
        if row["row_kind"] == "station"
    ]


def _date_text(value: Any) -> str:
    """Return the calendar day of a timestamp as text, or "" without one."""
    if value is None:
        return ""
    if hasattr(value, "date"):
        return str(value.date())
    return str(value)
