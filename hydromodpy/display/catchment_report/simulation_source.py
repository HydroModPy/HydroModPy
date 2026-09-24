"""Catalog-backed access to the simulation a catchment report describes.

The report reads the run through the catalog, not through an exported file:
automated exports are opt-in, so a run made with default settings has a
``timeseries`` table and a Parquet store but no CSV. Every path here is
resolved by the catalog, so the report survives a change of storage layout.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.core.state.paths import catalog_path_for

if TYPE_CHECKING:
    from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
    from hydromodpy.results.run import Run

DISCHARGE_VARIABLE = "discharge"


def catalog_file(inputs: CatchmentReportInputs) -> Path:
    """Return the catalog holding the simulation the report describes."""
    return catalog_path_for(Path(inputs.simulation_workspace_dir))


@contextmanager
def open_simulation_run(inputs: CatchmentReportInputs) -> Iterator[Run]:
    """Yield the report's run, opened read-only from the workspace catalog."""
    from hydromodpy.results.catalog import Catalog

    with Catalog(inputs.simulation_workspace_dir, read_only=True) as catalog:
        yield catalog[inputs.simulation_name]


def simulation_run_exists(inputs: CatchmentReportInputs) -> bool:
    """Return whether the report's run is registered in the catalog."""
    from hydromodpy.results.catalog.discovery import ReferenceResolutionError

    if not catalog_file(inputs).is_file():
        return False
    try:
        with open_simulation_run(inputs):
            return True
    except ReferenceResolutionError:
        return False


def newest_completed_run_name(inputs: CatchmentReportInputs) -> str | None:
    """Return the name of the newest completed run of the report's name stem.

    A registered name belongs to its run for good, a failed one included, so a
    rerun of the report's simulation lands under ``<stem>.vN``. ``None`` when
    the catalog holds no completed run of that stem, or when the configured
    name already names a version (``<stem>.vN``): a pinned run is read as
    written.
    """
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.registration import split_stem_version

    stem, version = split_stem_version(inputs.simulation_name)
    if version is not None or not catalog_file(inputs).is_file():
        return None
    with Catalog(inputs.simulation_workspace_dir, read_only=True) as catalog:
        runs = catalog.find(name_stem=stem, status="completed")
        return runs[0].name if len(runs) else None


def simulation_parquet_dir(run: Run) -> Path | None:
    """Return the run's Parquet directory when it exists on disk."""
    parquet_dir = run._catalog.tables_dir_for(run.sim_id)
    return parquet_dir if parquet_dir.is_dir() else None


def read_simulated_discharge(run: Run) -> pd.DataFrame:
    """Return the catchment discharge as ``datetime`` / ``value`` rows."""
    series = run.timeseries(DISCHARGE_VARIABLE)
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(pd.Index(series.index), errors="coerce"),
            "value": pd.to_numeric(series.to_numpy(), errors="coerce"),
        }
    )
    return frame.dropna(subset=["datetime", "value"]).sort_values("datetime")


__all__ = [
    "DISCHARGE_VARIABLE",
    "catalog_file",
    "newest_completed_run_name",
    "open_simulation_run",
    "read_simulated_discharge",
    "simulation_parquet_dir",
    "simulation_run_exists",
]
