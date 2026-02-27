"""Backward-compatible wrapper for `Workspace`."""

from hydromodpy.watershed.workspace import Workspace
from hydromodpy.watershed.workspace_config import WorkspaceConfig


class Initializing(Workspace):
    """Deprecated alias of :class:`Workspace` (kept for compatibility)."""


class InitializingConfig(WorkspaceConfig):
    """Deprecated alias of :class:`WorkspaceConfig` (kept for compatibility)."""


__all__ = ["Initializing", "InitializingConfig"]
