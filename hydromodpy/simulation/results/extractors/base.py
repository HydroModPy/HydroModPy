"""Protocol for output adapters that ingest solver files into ResultStore."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from hydromodpy.results.store import ResultStore


class OutputAdapter(Protocol):
    """Reads raw solver outputs and writes them into a ResultStore.

    Each concrete adapter handles one solver family (MODFLOW-NWT,
    MODFLOW 6, MT3DMS, MODPATH, GR4J, ...).

    The adapter lifecycle has two phases:
      1. **extract** — read binary/text solver files, inject fields,
         time series, budgets and mass balance into the store.
      2. **derive** — compute derived variables (watertable depth,
         seepage areas, ...) from the data already in the store.
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: ResultStore,
    ) -> None:
        """Phase 1: read solver outputs and write raw results to *store*."""
        ...

    def derive(
        self,
        sim_id: str,
        store: ResultStore,
        config: dict | None = None,
    ) -> None:
        """Phase 2: compute derived variables from stored results."""
        ...


def cleanup_solver_files(
    solver_output_dir: Path,
    keep: set[str] | None = None,
) -> None:
    """Remove solver working files, optionally keeping some extensions.

    Parameters
    ----------
    solver_output_dir : Path
        Directory containing raw solver files.
    keep : set[str], optional
        File extensions to keep (e.g. ``{".lst", ".nam"}``).
        If ``None``, the entire directory is removed.
    """
    if keep is None:
        shutil.rmtree(solver_output_dir, ignore_errors=True)
        return

    for f in solver_output_dir.iterdir():
        if f.is_file() and f.suffix not in keep:
            f.unlink(missing_ok=True)
    for d in solver_output_dir.iterdir():
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
