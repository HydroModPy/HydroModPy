"""Backward-compatibility shim for the old backends package.

The delineation backends have moved to
:mod:`hydromodpy.spatial.delineation`. Importing from this module still
works but emits a ``DeprecationWarning``. This shim will be removed in a
later migration phase (P13).
"""

from __future__ import annotations

import warnings

_WARNING = (
    "hydromodpy.core.backends is deprecated; "
    "import from hydromodpy.spatial.delineation instead."
)

__all__ = [
    "WhiteboxBackend",
    "WhiteboxWorkflowsBackend",
    "clear_whitebox_backend_cache",
    "get_whitebox_backend",
]


def __getattr__(name: str):
    if name in __all__:
        warnings.warn(_WARNING, DeprecationWarning, stacklevel=2)
        from hydromodpy.spatial.delineation import (
            WhiteboxBackend,
            WhiteboxWorkflowsBackend,
            clear_whitebox_backend_cache,
            get_whitebox_backend,
        )

        mapping = {
            "WhiteboxBackend": WhiteboxBackend,
            "WhiteboxWorkflowsBackend": WhiteboxWorkflowsBackend,
            "clear_whitebox_backend_cache": clear_whitebox_backend_cache,
            "get_whitebox_backend": get_whitebox_backend,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
