"""``[site] gauge`` as the station of the series sources of a catchment.

The station of a catchment is written once, in ``[site] gauge``. A series
source keyed by station (``custom`` chronicles or ``hubeau``) of the
variables in :data:`GAUGE_VARIABLES` takes the gauge when its
``station_ids`` is empty; a list that names another station and not the
gauge is refused with the name of the key. Without a gauge and with exactly
one station loaded, that station is the gauge of the run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.site import SiteConfig, resolve_gauge

GAUGE_VARIABLES: tuple[str, ...] = ("hydrometry", "recharge", "runoff")
"""The ``[data.<variable>]`` sections whose stations are the catchment station."""

_STATION_SOURCES = frozenset({"custom", "hubeau"})
_GRID_SUFFIXES = frozenset({".nc", ".tif", ".tiff"})


def apply_site_gauge(data: Any, site: SiteConfig | None) -> None:
    """Fill the empty ``station_ids`` of the station sources with ``site.gauge``.

    ``data`` is the ``[data]`` section of a project. A source that lists
    stations without the gauge raises :class:`GaugeConflictError` naming
    ``site.gauge`` and the key, such as ``data.hydrometry.sources[0].station_ids``.
    A source that reads a grid file is left alone.
    """
    if data is None:
        return
    for variable in GAUGE_VARIABLES:
        section = getattr(data, variable, None)
        if section is None:
            continue
        for index, source in enumerate(section.sources):
            if not _keyed_by_station(source):
                continue
            declared = source.station_ids
            gauge = resolve_gauge(
                site, declared, field=f"data.{variable}.sources[{index}].station_ids"
            )
            if not declared and gauge is not None:
                source.station_ids = [gauge]


def gauge_of_run(site: SiteConfig | None, hydrometry: Any) -> str | None:
    """Return the gauge a run records: ``site.gauge``, else its single station.

    ``hydrometry`` is the ``LoadResult`` of ``[data.hydrometry]``, or None. With
    no gauge declared and exactly one station loaded, that station is the
    gauge; with none or several, the run has no gauge.
    """
    if site is not None and site.gauge is not None:
        return site.gauge
    points = list(getattr(hydrometry, "points", None) or ())
    if len(points) != 1:
        return None
    return str(points[0].station_id)


def check_run_gauge_area(
    site: SiteConfig | None,
    hydrometry: Any,
    catchment_area_km2: float | None,
) -> None:
    """Warn when the delineated area disagrees with the one the run's gauge publishes.

    The gauge is :func:`gauge_of_run`. A run with several stations and no
    ``[site] gauge`` has none, so nothing is checked.
    """
    from hydromodpy.data.variables.hydrometry.catchment_area_check import check_gauge_area

    check_gauge_area(gauge_of_run(site, hydrometry), catchment_area_km2)


def _keyed_by_station(source: Any) -> bool:
    """True for a source whose ``station_ids`` selects catchment stations."""
    if getattr(source, "source", None) not in _STATION_SOURCES:
        return False
    path = getattr(source, "path", None)
    return path is None or Path(str(path)).suffix.lower() not in _GRID_SUFFIXES


__all__ = ["GAUGE_VARIABLES", "apply_site_gauge", "check_run_gauge_area", "gauge_of_run"]
