"""Deprecated: moved to ``hydromodpy.spatial.delineation.whitebox_workflows_backend``."""

from __future__ import annotations

import warnings

warnings.warn(
    "hydromodpy.core.backends.whitebox_workflows_backend is deprecated; "
    "import from hydromodpy.spatial.delineation instead.",
    DeprecationWarning,
    stacklevel=2,
)

from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
    WhiteboxWorkflowsBackend,
    clear_whitebox_backend_cache,
    get_whitebox_backend,
)

__all__ = [
    "WhiteboxWorkflowsBackend",
    "clear_whitebox_backend_cache",
    "get_whitebox_backend",
]
