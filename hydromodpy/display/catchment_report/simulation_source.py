"""Access to the simulation a catchment report describes, by its run directory.

The report reads the run from its directory, never from the index nor from an
exported file: automated exports are opt-in, so a run made with default
settings has a ``timeseries`` table and a field store but no CSV. Which runs
exist and which completed is read on disk: a completed run is a directory
holding its ``manifest.json``. The sealed run is opened through its
:class:`~hydromodpy.results.storage.run_store.RunStore`, which reads its
facts from the manifest and writes nothing back.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.core.scope import SIMULATED
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.manifest import is_sealed

if TYPE_CHECKING:
    from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
    from hydromodpy.results.storage.run_store import RunStore

DISCHARGE_VARIABLE = "discharge"


@contextmanager
def open_simulation_run(inputs: CatchmentReportInputs) -> Iterator[RunStore]:
    """Yield the store of the report's sealed run, read from its directory."""
    from hydromodpy.results.storage.run_store import RunStore

    with RunStore.open(inputs.run_dir) as store:
        yield store


def simulation_run_exists(inputs: CatchmentReportInputs) -> bool:
    """Return whether the report's run completed: its directory holds ``manifest.json``."""
    return is_sealed(inputs.run_dir)


def newest_completed_run_name(inputs: CatchmentReportInputs) -> str | None:
    """Return the name of the newest completed run of the report's name stem.

    A name belongs to its run for good, a failed one included, so a rerun of
    the report's simulation lands under ``<stem>.vN``. ``None`` when no run of
    that stem completed, or when the configured name already names a version
    (``<stem>.vN``): a pinned run is read as written.
    """
    stem, version = split_stem_version(inputs.simulation_name)
    runs = runs_dir_for(Path(inputs.simulation_workspace_dir))
    if version is not None or not runs.is_dir():
        return None
    completed: list[tuple[int, str]] = []
    for candidate in runs.iterdir():
        name_stem, name_version = split_stem_version(candidate.name)
        if name_stem == stem and is_sealed(candidate):
            completed.append((name_version or 1, candidate.name))
    return max(completed)[1] if completed else None


def simulation_parquet_dir(store: RunStore) -> Path | None:
    """Return the run's Parquet directory when it exists on disk."""
    return store.tables_dir if store.tables_dir.is_dir() else None


def read_simulated_discharge(store: RunStore) -> pd.DataFrame:
    """Return the catchment discharge as ``datetime`` / ``value`` rows.

    Raises
    ------
    KeyError
        The run stored no discharge, or stored it at several stations.
    """
    frame = store.read_table("timeseries")
    rows = (
        frame[(frame["variable"] == DISCHARGE_VARIABLE) & (frame["source"] == SIMULATED)]
        if not frame.empty
        else frame
    )
    stations = sorted({str(station) for station in rows.get("station_id", [])})
    if not stations:
        raise KeyError(f"run {store.run_dir.name} stored no {DISCHARGE_VARIABLE} series")
    if len(stations) > 1:
        raise KeyError(
            f"run {store.run_dir.name} stored {DISCHARGE_VARIABLE} at several stations "
            f"({', '.join(stations)}); a catchment report reads one."
        )
    times = pd.to_datetime(rows["time"], utc=True, errors="coerce")
    result = pd.DataFrame(
        {
            "datetime": times.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(),
            "value": pd.to_numeric(rows["value"], errors="coerce").to_numpy(),
        }
    )
    return result.dropna(subset=["datetime", "value"]).sort_values("datetime")


__all__ = [
    "DISCHARGE_VARIABLE",
    "newest_completed_run_name",
    "open_simulation_run",
    "read_simulated_discharge",
    "simulation_parquet_dir",
    "simulation_run_exists",
]
