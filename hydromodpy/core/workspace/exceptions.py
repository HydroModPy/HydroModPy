"""Workspace-resolution errors."""

from __future__ import annotations


class WorkspaceError(RuntimeError):
    """Raised when no HydroModPy workspace can be located for a given TOML."""
