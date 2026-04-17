"""Backend adapters for optional third-party runtime dependencies."""

from __future__ import annotations

from hydromodpy.core.backends.whitebox_backend import WhiteboxBackend

__all__ = [
    "WhiteboxBackend",
    "WhiteboxWorkflowsBackend",
    "clear_whitebox_backend_cache",
    "get_whitebox_backend",
]


def __getattr__(name: str):
    if name in {
        "WhiteboxWorkflowsBackend",
        "clear_whitebox_backend_cache",
        "get_whitebox_backend",
    }:
        from hydromodpy.core.backends.whitebox_workflows_backend import (
            WhiteboxWorkflowsBackend,
            clear_whitebox_backend_cache,
            get_whitebox_backend,
        )

        mapping = {
            "WhiteboxWorkflowsBackend": WhiteboxWorkflowsBackend,
            "clear_whitebox_backend_cache": clear_whitebox_backend_cache,
            "get_whitebox_backend": get_whitebox_backend,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
