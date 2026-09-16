"""Finding the observations a simulated series should be judged against.

A simulated catchment series lives at the pseudo-station ``_catchment``; the
measurement it answers to lives at the id of the gauge that recorded it. Asking
for observations at the simulated station therefore finds nothing, which is why
a comparison figure has to be told, or has to work out, which station holds the
other half.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


def observed_series(
    sim: Run,
    variable: str,
    *,
    station: str | None = None,
    label: str = "figure",
) -> tuple[pd.Series, str]:
    """Return the observed series of ``variable`` and the station it came from.

    With ``station`` given, that station is read and nothing is guessed. Without
    it, every station observing the variable is offered: one is taken, several
    are refused by name rather than picked at random.
    """
    rows = sim.observed(variable, station=station)
    if rows.empty:
        raise ValueError(f"{label}: no observed {variable!r} for sim {sim.sim_id}")

    stations = sorted(str(value) for value in rows["station_id"].unique())
    if station is None and len(stations) > 1:
        raise ValueError(
            f"{label}: {len(stations)} stations observe {variable!r} "
            f"({', '.join(stations)}); name one with observed_station"
        )
    resolved = station if station is not None else stations[0]

    series = pd.Series(
        rows["value"].to_numpy(dtype="float64"),
        index=pd.DatetimeIndex(rows["datetime"]),
        name=variable,
    ).sort_index()
    return series, resolved
