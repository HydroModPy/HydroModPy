"""Workspace-resolution errors."""

from __future__ import annotations

from hydromodpy.core.exceptions import ConfigError


class WorkspaceError(ConfigError, RuntimeError):
    """Raised when no HydroModPy workspace can be located for a given TOML."""
