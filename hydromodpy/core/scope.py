"""The words the stored tables share.

``catchment`` is the whole catchment and the only word for it, in every table
and every store: the station of a catchment series, the zone of a budget row or
of a uniform parameter, the soil column of the basin mean, the forcing station of
the basin mean. ``domain`` is the whole model domain, a budget zone. The two are
not the same surface when the mesh takes in a buffer around the catchment.

``simulated`` and ``observed`` are the values of the ``source`` column of the
``timeseries`` table: a series and the measurement it answers to carry the same
variable name. A reader that asks by one name, ``hmp.read`` and ``[[export]]``,
asks for the measurement as ``<variable>_obs``, which no table stores.

A station or a zone a user names cannot be called ``catchment``, because a reader
would take it for the whole catchment: a gauge would be scored against the outlet, a
zone would read as a uniform parameter. ``domain`` stays free. Only a budget row reads
it, a budget zone is never a name a user gives, and it is a label of the
``catchment_zones`` support.
"""

from __future__ import annotations

from typing import Final

CATCHMENT: Final[str] = "catchment"
"""The whole catchment."""

DOMAIN: Final[str] = "domain"
"""The whole model domain, the budget zone a solver sums over every cell."""

SIMULATED: Final[str] = "simulated"
"""A value the run computed."""

OBSERVED: Final[str] = "observed"
"""A value measured in the field and stored beside the simulated one."""

_OBSERVED_NAME = "_obs"


def series_name(variable: str, source: str) -> str:
    """Return the name a reader asks for one series by."""
    return f"{variable}{_OBSERVED_NAME}" if source == OBSERVED else variable


def series_selector(name: str) -> tuple[str, str]:
    """Return the ``(variable, source)`` a series name stands for."""
    if name.endswith(_OBSERVED_NAME):
        return name[: -len(_OBSERVED_NAME)], OBSERVED
    return name, SIMULATED


def station_name_refusal(name: object) -> str | None:
    """Return why ``name`` cannot name a station, ``None`` when it can."""
    if str(name).strip() != CATCHMENT:
        return None
    return (
        f"{CATCHMENT!r} cannot name a station: it stands for the whole catchment, so a gauge "
        "with this name would be scored against the simulated outlet. Write the gauge code, "
        'such as "J0014010".'
    )


def zone_name_refusal(name: object) -> str | None:
    """Return why ``name`` cannot name a zone of a parameter, ``None`` when it can."""
    if str(name).strip() != CATCHMENT:
        return None
    return (
        f"{CATCHMENT!r} cannot name a zone: a run stores a uniform parameter under this word, "
        "so the zone would read as the value of the whole model. Name the zone after what it "
        'holds, such as "core" or "hillslope".'
    )


__all__ = [
    "CATCHMENT",
    "DOMAIN",
    "OBSERVED",
    "SIMULATED",
    "series_name",
    "series_selector",
    "station_name_refusal",
    "zone_name_refusal",
]
