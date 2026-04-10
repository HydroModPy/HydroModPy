"""Backward-compatible re-export of shared MODFLOW option dataclasses."""

from __future__ import annotations

from hydromodpy.solver.modflow_common.options import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)

__all__ = [
    "ModflowPreprocessOptions",
    "ModflowRunOptions",
    "ModflowPostprocessOptions",
]
