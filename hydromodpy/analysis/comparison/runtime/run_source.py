"""One sealed run, read from its own directory.

A comparison reads runs that already finished. Each one is a directory sealed
by its ``manifest.json``: the arrays sit in ``fields.zarr``, the tables in
``tables.parquet/``, the frozen configuration in ``config.toml``.
:class:`RunSource` reads them there and nowhere else. A comparison never opens
the project index, never writes into a run, and works the same on a run copied
out of its project.

The readers of the analysis (``runtime/series.py``, ``runtime/mesh.py``,
``exports/``) take a source with the ``open_zarr`` / ``query_field`` /
``query_budget`` verbs; :class:`RunSource` is that source for one run.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.results.derive.virtual_fields import read_field_or_virtual
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    RUN_CONFIG_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

BUDGETS_TABLE_NAME = "budgets"
"""Parquet table of the water budget of a run, ``tables.parquet/budgets.parquet``."""

TIMESERIES_TABLE_NAME = "timeseries"
"""Parquet table of the simulated series of a run, ``tables.parquet/timeseries.parquet``."""


class RunNotComparableError(ValueError):
    """A directory given to a comparison is not a sealed run."""


class RunSource:
    """Read-only access to the arrays and tables of one sealed run."""

    def __init__(self, run_dir: Path, record: RunRecord) -> None:
        self._run_dir = run_dir
        self._record = record
        self._handles: list[SimulationZarr] = []

    @classmethod
    def open(cls, run_dir: str | Path) -> RunSource:
        """Open the sealed run in *run_dir*.

        Raises :class:`RunNotComparableError` when the directory has no
        ``manifest.json``: only a completed run carries a seal.
        """
        directory = Path(run_dir).expanduser().resolve()
        if not is_sealed(directory):
            raise RunNotComparableError(
                f"{directory} holds no {RUN_MANIFEST_FILENAME}: only a completed, sealed run "
                f"can be compared. Read its {RUN_OUTCOME_FILENAME} for what happened."
            )
        return cls(directory, RunRecord.read(directory))

    @property
    def run_dir(self) -> Path:
        """The sealed run directory."""
        return self._run_dir

    @property
    def record(self) -> RunRecord:
        """The seal of the run, as its ``manifest.json`` gives it."""
        return self._record

    @property
    def sim_id(self) -> str:
        """The id of the run."""
        return self._record.run.sim_id

    @property
    def config_path(self) -> Path:
        """The frozen resolved configuration of the run."""
        return self._run_dir / RUN_CONFIG_FILENAME

    def fields_path_for(self, sim_id: str | None = None) -> Path:
        """Return the Zarr directory store of the run."""
        return self._run_dir / FIELDS_STORE_NAME

    def open_zarr(self, sim_id: str | None = None) -> SimulationZarr:
        """Open the field store of the run. The handle is closed by :meth:`close`.

        Raises ``FileNotFoundError`` when the run stored no ``fields.zarr``.
        """
        fields = self.fields_path_for()
        if not fields.is_dir():
            raise FileNotFoundError(f"Run {self._run_dir.name} has no {FIELDS_STORE_NAME}")
        handle = SimulationZarr(fields)
        self._handles.append(handle)
        return handle

    def query_field(
        self,
        sim_id: str,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        """Return one timestep of a stored or derived field."""
        return read_field_or_virtual(self, self.sim_id, variable, timestep, layer=layer)

    def table_path(self, name: str) -> Path:
        """Return ``tables.parquet/<name>.parquet`` of the run."""
        return self._run_dir / TABLES_DIRNAME / f"{name}{PARQUET_FILE_SUFFIX}"

    def read_table(self, name: str) -> pd.DataFrame:
        """Return one Parquet table of the run, empty when the run stored none."""
        path = self.table_path(name)
        if not path.is_file():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def query_budget(
        self,
        sim_id: str | None = None,
        zone_id: str | None = None,
        period: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
        """Return the water budget rows of the run, empty when it stored none.

        ``period`` is ``(first, last)`` timestep indexes, both included.
        """
        frame = self.read_table(BUDGETS_TABLE_NAME)
        if frame.empty:
            return frame
        if zone_id is not None and "zone_id" in frame.columns:
            frame = frame.loc[frame["zone_id"] == zone_id]
        if period is not None and "timestep" in frame.columns:
            first, last = period
            frame = frame.loc[(frame["timestep"] >= first) & (frame["timestep"] <= last)]
        return frame.reset_index(drop=True)

    def close(self) -> None:
        """Close every field store this source opened."""
        while self._handles:
            self._handles.pop().close()

    def __enter__(self) -> RunSource:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def open_run_source(summary: Mapping[str, Any]) -> RunSource | None:
    """Open the run a simulation summary of a comparison names, or None.

    A summary names its run by ``run_dir``; a summary without one, or whose
    directory holds no seal, has nothing to read.
    """
    raw = summary.get("run_dir")
    if raw in (None, ""):
        return None
    try:
        return RunSource.open(Path(str(raw)))
    except RunNotComparableError:
        return None


def open_run(summary: Mapping[str, Any]) -> Run | None:
    """Open the run a simulation summary of a comparison names, as a ``Run``, or None.

    The network metrics and the network figures read a run through
    :class:`~hydromodpy.results.run.Run`. It is opened on its sealed directory,
    the way ``hmp.open(<run dir>)`` opens it: the index of the project is never
    read, so a run copied out of its project or a project never indexed reads
    the same. A summary without a sealed ``run_dir`` has nothing to read.
    """
    from hydromodpy.results.run.view import open_run_dir

    raw = summary.get("run_dir")
    if raw in (None, ""):
        return None
    directory = Path(str(raw))
    if not is_sealed(directory):
        return None
    return open_run_dir(directory)


__all__ = (
    "BUDGETS_TABLE_NAME",
    "TIMESERIES_TABLE_NAME",
    "RunNotComparableError",
    "RunSource",
    "open_run",
    "open_run_source",
)
