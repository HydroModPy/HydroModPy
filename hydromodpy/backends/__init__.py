"""Backend adapters for optional third-party runtime dependencies.

This package exposes the backend protocol used by HydroModPy runtime code and
the default WhiteboxTools-based implementation.  Callers should generally
import backend symbols from here instead of reaching into implementation files.
"""

from hydromodpy.backends.whitebox_backend import WhiteboxBackend
from hydromodpy.backends.whitebox_tools_backend import (
    WhiteboxToolsBackend,
    get_whitebox_backend,
)

try:
    from hydromodpy.backends.whitebox_workflows_backend import WhiteboxWorkflowsBackend
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    WhiteboxWorkflowsBackend = None

__all__ = [
    "WhiteboxBackend",
    "WhiteboxToolsBackend",
    "WhiteboxWorkflowsBackend",
    "get_whitebox_backend",
]
