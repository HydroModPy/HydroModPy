"""Check a delineated catchment against the drainage area its gauge publishes.

A gauge closes a catchment, and Hub'Eau publishes the area that catchment has:
``surface_bv`` on ``/referentiel/sites``, in km2. Comparing it to the area the
run delineated is the only cheap check that catches an outlet placed on the
wrong branch of a confluence, which is the failure a distance criterion cannot
see. Two points forty metres apart can sit on two different streams, and their
catchments then differ by an order of magnitude, not by forty metres.

The endpoint the rest of the hydrometry code calls is ``referentiel/stations``,
which carries no area at all. The area lives one level up, on the SITE a station
belongs to: a station code is its site code plus a two-digit suffix.

Measured on the Nancon, site ``J0014010``: ``surface_bv`` is 64.45 km2 against
64.61 km2 delineated at 75 m, a 0.24 per cent gap.
"""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

API_BASE = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"


@dataclass(frozen=True)
class CatchmentAreaComparison:
    """What the gauge publishes against what the run delineated."""

    site_id: str
    published_km2: float
    delineated_km2: float

    @property
    def relative_gap(self) -> float:
        """Signed relative gap, delineated against published."""
        return (self.delineated_km2 - self.published_km2) / self.published_km2

    def __str__(self) -> str:
        return (
            f"site {self.site_id}: {self.delineated_km2:.2f} km2 delineated against "
            f"{self.published_km2:.2f} km2 published, {self.relative_gap:+.1%}"
        )


def site_id_of_station(station_id: str) -> str:
    """Return the site a station belongs to.

    A Hub'Eau hydrometry station code is its site code plus a two-digit station
    number, so ``J001401001`` is station 01 of site ``J0014010``. A code already
    of site length is returned unchanged.
    """
    cleaned = str(station_id).strip().upper()
    return cleaned[:-2] if len(cleaned) > 8 else cleaned


def published_catchment_area_km2(station_id: str) -> float | None:
    """Return the drainage area Hub'Eau publishes for a station's site, in km2.

    ``None`` when the site is unknown, carries no area, or the service cannot be
    reached: this is a cross-check, and losing it must never fail a run.
    """
    from hydromodpy.data.common.api_client import get_json

    site_id = site_id_of_station(station_id)
    try:
        payload = get_json(
            f"{API_BASE}/referentiel/sites",
            params={"code_site": site_id, "size": 1, "format": "json"},
        )
    except Exception:
        logger.debug("Could not read the Hub'Eau site of %s", station_id, exc_info=True)
        return None
    rows = (payload or {}).get("data") or []
    if not rows:
        return None
    area = rows[0].get("surface_bv")
    if area is None:
        return None
    try:
        value = float(area)
    except (TypeError, ValueError):
        return None
    return value if value > 0.0 else None


def compare_catchment_area(
    station_id: str,
    delineated_km2: float,
    *,
    warn_relative_gap: float = 0.10,
) -> CatchmentAreaComparison | None:
    """Compare a delineated catchment to its gauge's published area, and warn.

    Returns ``None`` when no published area is available, which is not a
    failure. A gap beyond ``warn_relative_gap`` warns rather than raises: the
    published area and a D8 delineation on a coarse DEM legitimately differ by a
    few per cent, and only the user knows which one to trust.
    """
    if delineated_km2 <= 0.0:
        raise ValueError(f"a delineated catchment area must be positive, got {delineated_km2}.")
    published = published_catchment_area_km2(station_id)
    if published is None:
        return None

    comparison = CatchmentAreaComparison(
        site_id=site_id_of_station(station_id),
        published_km2=published,
        delineated_km2=float(delineated_km2),
    )
    if abs(comparison.relative_gap) > float(warn_relative_gap):
        logger.warning(
            "Catchment area disagrees with the gauge: %s. An outlet on the wrong branch of a "
            "confluence looks like this, and a distance to the station cannot show it. Check "
            "geographic.x_outlet / y_outlet and snap_dist against the station position.",
            comparison,
        )
    else:
        logger.info("Catchment area agrees with the gauge: %s.", comparison)
    return comparison


__all__ = [
    "CatchmentAreaComparison",
    "compare_catchment_area",
    "published_catchment_area_km2",
    "site_id_of_station",
]
