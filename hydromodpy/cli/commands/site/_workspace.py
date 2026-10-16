"""Find the workspace whose site catalog an ``hmp site`` action reads or writes."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_data_workspace
from hydromodpy.core.state.paths import is_workspace_root


def workspace_root(workspace_arg: str | None) -> Path:
    """Return the workspace named by ``-w``, ``HMP_WORKSPACE`` or the current folder.

    A project folder resolves to the workspace above it. Without a workspace
    the command stops: a site catalog is never written to a default folder.
    """
    if workspace_arg:
        start = Path(workspace_arg).expanduser().resolve()
    elif os.environ.get("HMP_WORKSPACE"):
        start = Path(os.environ["HMP_WORKSPACE"]).expanduser().resolve()
    else:
        start = Path.cwd().resolve()
    found = find_data_workspace(start)
    if found is None and is_workspace_root(start):
        found = start
    if found is None:
        print(
            f"No HydroModPy workspace at or above {start}. Name one with -w, "
            "or run 'hmp workspace init' first.",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)
    return found
