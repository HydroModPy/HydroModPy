"""Core infrastructure layer for HydroModPy."""

from hydromodpy.core.config import HydroModPyConfig
from hydromodpy.core.state import (
    ExecutionRegistry,
    LauncherRunState,
    LoadedDataContext,
    SetupContext,
)
from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.core.workspace import Workspace, WorkspaceConfig, WorkspacePathRegistry

__all__ = [
    "HydroModPyConfig",
    "Workspace",
    "WorkspaceConfig",
    "WorkspacePathRegistry",
    "ExecutionRegistry",
    "LauncherRunState",
    "LoadedDataContext",
    "SetupContext",
    "ResolvedSimulationTimeWindow",
    "WhiteboxBackend",
    "WhiteboxWorkflowsBackend",
    "clear_whitebox_backend_cache",
    "get_whitebox_backend",
]


def __getattr__(name: str):
    if name in {
        "WhiteboxBackend",
        "WhiteboxWorkflowsBackend",
        "clear_whitebox_backend_cache",
        "get_whitebox_backend",
    }:
        from hydromodpy.core.backends import (
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
