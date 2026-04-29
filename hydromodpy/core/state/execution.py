"""Runtime execution scope shared by launcher process runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExecutionRegistry:
    """Execution-oriented metadata and produced model registry.

    ``lightweight`` is set to ``True`` when the pipeline runs inside a
    calibration trial: in that mode steps 06/07 skip Zarr / Parquet /
    provenance writes and the solver output is kept in RAM for scoring
    only. The flag is ``False`` for normal ``hmp run`` and for promoted
    trials.

    ``output_dirs_by_run_id`` mirrors ``models_by_run_id`` and records
    the raw solver output directory emitted by each run. Calibration
    metric extractors read the solver binaries (``.hds`` / ``.cbc``)
    directly from these paths without touching the catalog.

    Field types are ``Any`` because ``core`` cannot import from sibling
    layers. ``simulation_plan``, ``process_runs_by_id`` values, and
    ``models_by_run_id`` values are produced by the ``simulation`` and
    ``solver`` layers respectively.
    """

    simulation_plan: Any = None
    process_runs_by_id: dict[str, Any] = field(default_factory=dict)
    models_by_run_id: dict[str, Any] = field(default_factory=dict)
    output_dirs_by_run_id: dict[str, Path] = field(default_factory=dict)
    lightweight: bool = False
