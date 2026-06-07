"""In-memory cache for lumped-model lightweight extraction.

Lumped catchment models (GR4J, ...) finish a trial with their full simulated
time series already in RAM. Writing them to Parquet/DuckDB for every trial is
wasted I/O during calibration: only the metric extractor needs the values, and
only the best promoted trial deserves the full catalog row.

``LumpedRamCache`` is a tiny attribute attached to the trial execution
registry. A solver run stores its hot series there via :func:`stash_series`
and the calibration adapter reads them back through :func:`load_series`.

The cache lives **for one trial only**. Forking a :class:`TrialContext`
spawns a fresh registry and therefore a fresh cache so trials never see
each others' series.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class LumpedRamCache:
    """Per-trial in-memory store of simulated series keyed by ``(station, variable)``."""

    series: dict[tuple[str, str], pd.Series] = field(default_factory=dict)

    def put(self, station_id: str, variable: str, value: pd.Series) -> None:
        """Cache ``value`` under ``(station_id, variable)``."""
        self.series[(str(station_id), str(variable))] = value

    def get(self, station_id: str, variable: str) -> pd.Series | None:
        """Return the cached series for ``(station_id, variable)`` or ``None``."""
        return self.series.get((str(station_id), str(variable)))

    def __contains__(self, key: tuple[str, str]) -> bool:
        return (str(key[0]), str(key[1])) in self.series

    def __len__(self) -> int:
        return len(self.series)


def stash_series(
    execution: Any,
    station_id: str,
    variable: str,
    series: pd.Series,
) -> None:
    """Push a hot simulated series into the trial's ``LumpedRamCache``.

    Creates the cache lazily on the execution registry so callers do not need
    to initialise it upfront.
    """
    cache = getattr(execution, "lumped_ram_cache", None)
    if cache is None:
        cache = LumpedRamCache()
        execution.lumped_ram_cache = cache
    cache.put(station_id, variable, series)


def load_series(
    execution: Any,
    station_id: str,
    variable: str,
) -> pd.Series | None:
    """Read a hot simulated series from the trial's ``LumpedRamCache``."""
    cache = getattr(execution, "lumped_ram_cache", None)
    if cache is None:
        return None
    return cache.get(station_id, variable)


__all__ = ["LumpedRamCache", "stash_series", "load_series"]
