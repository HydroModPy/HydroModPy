"""HydroModPy pipeline - orchestration, checkpointing, resume.

This package provides a single ``Pipeline`` orchestrator that runs a list of
``Step`` objects sequentially. State flows between steps via
``PipelineState`` (a frozen, generic, serializable dataclass).

The pipeline writes a DuckDB ``steps`` ledger and optionally serializes
``PipelineState`` to disk so a crashed run can be resumed with
``Pipeline.run(state, resume_from=<index>)``.
"""

from __future__ import annotations

from hydromodpy.workflow.internals import derived
from hydromodpy.workflow.internals.derived import DerivedRegistry
from hydromodpy.workflow.internals.state import (
    DerivedState,
    ExportedState,
    ExtractedState,
    LoadedState,
    MeshedState,
    OpenStoreState,
    PipelineState,
    ResolvedState,
    SetupState,
    SolverRanState,
    ValidatedState,
)
from hydromodpy.workflow.internals.step import Step
from hydromodpy.workflow.runner import Pipeline

__all__ = (
    "DerivedRegistry",
    "DerivedState",
    "ExportedState",
    "ExtractedState",
    "LoadedState",
    "MeshedState",
    "OpenStoreState",
    "Pipeline",
    "PipelineState",
    "ResolvedState",
    "SetupState",
    "SolverRanState",
    "Step",
    "ValidatedState",
    "derived",
)
