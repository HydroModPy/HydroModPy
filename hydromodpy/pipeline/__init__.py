"""HydroModPy pipeline — orchestration, checkpointing, resume.

This package provides a single ``Pipeline`` orchestrator that runs a list of
``Step`` objects sequentially. State flows between steps via
``PipelineState`` (a frozen, serializable dataclass).

The pipeline writes a DuckDB ``steps`` ledger and optionally serializes
``PipelineState`` to disk so a crashed run can be resumed with
``Pipeline.run(state, resume_from=<index>)``.
"""

from __future__ import annotations

from hydromodpy.pipeline.pipeline import Pipeline
from hydromodpy.pipeline.state import PipelineState
from hydromodpy.pipeline.step import Step

__all__ = ("Pipeline", "PipelineState", "Step")
