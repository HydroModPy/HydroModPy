"""Helpers shared by the four Hub'Eau providers.

Each variable keeps its own endpoint, discovery and download in
``variables/<v>/apis/hubeau.py``; what they share is how a station's active
period is read and how the nearest station to a point is kept.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from hydromodpy.core import progress
from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.geo_helpers import haversine_km

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hydromodpy.data.contracts.location import StationLocation

logger = get_logger(__name__)


def station_period_overlaps(
    station_start: str | None,
    station_end: str | None,
    req_start: datetime,
    req_end: datetime,
) -> bool:
    """True unless the station's dates show it closed before or opened after the window.

    Hub'Eau writes the dates as ISO strings; a date that does not parse says
    nothing, and the station is kept.
    """
    start = _iso_date(station_start)
    if start is not None and start > req_end:
        return False
    end = _iso_date(station_end)
    return end is None or end >= req_start


def _iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10])
    except (ValueError, TypeError) as exc:
        logger.debug("Could not parse Hub'Eau station date %r: %s", value, exc)
        return None


def keep_nearest(
    ids: Sequence[str],
    nearest_to: tuple[float, float],
    locate: Callable[[str], StationLocation | None],
    *,
    label: str,
) -> list[str]:
    """Keep only the station closest to ``nearest_to`` ``(lon, lat)``, located by ``locate``."""
    target_lon, target_lat = nearest_to
    best_id: str | None = None
    best_dist = float("inf")
    for station_id in progress.track(list(ids), f"Locating {label} stations"):
        location = locate(station_id)
        if location is None:
            continue
        dist = haversine_km(target_lon, target_lat, location.x, location.y)
        if dist < best_dist:
            best_dist = dist
            best_id = station_id
    if best_id is None:
        return []
    logger.info(
        "Hub'Eau %s: nearest to (%.4f, %.4f) -> %s (%.1f km)",
        label,
        target_lon,
        target_lat,
        best_id,
        best_dist,
    )
    return [best_id]


__all__ = ["keep_nearest", "station_period_overlaps"]
