"""Backward-compatible wrapper for `WorkspaceConfig`."""

from hydromodpy.watershed.workspace_config import WorkspaceConfig


class InitializingConfig(WorkspaceConfig):
    """Deprecated alias of :class:`WorkspaceConfig` (kept for compatibility)."""


__all__ = ["InitializingConfig"]
