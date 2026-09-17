"""Core infrastructure layer for HydroModPy.

Keep this package-level module lightweight: importing ``hydromodpy.core``
should not eagerly pull the full configuration and data-loading stack.
``core`` is the kernel leaf of the import DAG and must not re-export
symbols from sibling layers.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "Workspace",
    "WorkspaceConfig",
    "WorkspacePathRegistry",
    "ExecutionRegistry",
    "WorkflowContext",
    "LoadedDataContext",
    "SetupContext",
    "ResolvedSimulationTimeWindow",
]

_LAZY_IMPORTS = {
    "Workspace": "hydromodpy.core.workspace:Workspace",
    "WorkspaceConfig": "hydromodpy.core.workspace:WorkspaceConfig",
    "WorkspacePathRegistry": "hydromodpy.core.workspace:WorkspacePathRegistry",
    "ExecutionRegistry": "hydromodpy.core.state:ExecutionRegistry",
    "WorkflowContext": "hydromodpy.core.state:WorkflowContext",
    "LoadedDataContext": "hydromodpy.core.state:LoadedDataContext",
    "SetupContext": "hydromodpy.core.state:SetupContext",
    "ResolvedSimulationTimeWindow": "hydromodpy.core.time:ResolvedSimulationTimeWindow",
}


def __getattr__(name: str) -> Any:
    try:
        target = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module_path, attr_name = target.split(":", 1)
    module = import_module(module_path)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
