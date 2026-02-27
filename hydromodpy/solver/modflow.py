"""Backward-compatible shim for MODFLOW imports."""

from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowConfig,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)

__all__ = [
    "Modflow",
    "ModflowConfig",
    "ModflowPreprocessOptions",
    "ModflowRunOptions",
    "ModflowPostprocessOptions",
]
