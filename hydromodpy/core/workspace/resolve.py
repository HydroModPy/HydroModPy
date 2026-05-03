"""Best-effort workspace-root lookup for runtime code.

Used by solver-side and analysis helpers that need to re-open a workspace
catalog from a project directory on disk (e.g. MODPATH replaying a
previous solve). This is a **read-only** lookup - it does not drive the
strict binary resolution of ``WorkspaceConfig``.

Lookup strategy (first match wins):

1. ``HYDROMODPY_WORKSPACE`` environment variable if it points at a
   directory.
2. ``<project_root>/../..`` when ``project_root.parent.name == "projects"``
   and the grand-grand-parent contains ``data/``.

Returns ``None`` when no workspace can be found - callers fall back to
the project_root directly.
"""

from __future__ import annotations

import os
from pathlib import Path


def locate_workspace_root(project_root: Path | str) -> Path | None:
    """Best-effort lookup, returning ``None`` on miss."""
    env = os.environ.get("HYDROMODPY_WORKSPACE")
    if env:
        env_path = Path(env).expanduser()
        if env_path.is_dir():
            return env_path.resolve()

    resolved = Path(project_root).expanduser().resolve()
    if resolved.parent.name == "projects":
        candidate = resolved.parent.parent
        if (candidate / "data").is_dir():
            return candidate
    return None
