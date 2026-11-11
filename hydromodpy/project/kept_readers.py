"""The three readers the top level keeps beside the verbs: read, index and Catalog.

The frozen runs of 2.0.0 are read through ``hmp.read``, ``hmp.index`` and
``hmp.Catalog``, so these names stay. They are not verbs: ``read`` gives what
``Run.read`` gives, ``index`` opens a workspace and ``Catalog`` is the index of
a project.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hydromodpy.core.state.layout import is_workspace_root
from hydromodpy.project.accessors import Workspace
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run.view import Run

__all__ = ["read", "index", "Catalog"]


def read(
    run: Run,
    variable: str,
    *,
    time: Any = None,
    layer: int | None = None,
    sel: dict | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> Any:
    """Read a variable of a run, as :meth:`hydromodpy.results.run.view.Run.read` does.

    >>> import hydromodpy as hmp
    >>> head = hmp.read(run, "head", time=-1, layer=0)  # doctest: +SKIP
    """
    if not isinstance(run, Run):
        raise TypeError(f"hmp.read takes a Run, got {type(run).__name__}")
    return run.read(variable, time=time, layer=layer, sel=sel, bbox=bbox)


def index(workspace: str | os.PathLike[str] | None = None) -> Workspace:
    """Open the workspace at or above ``workspace``, read only.

    The working directory is the start when ``workspace`` is None. It raises
    ``FileNotFoundError`` when no folder above holds ``workspace.toml`` or ``projects/``.

    >>> import hydromodpy as hmp
    >>> hmp.index("~/ws").runs(site="nancon")  # doctest: +SKIP
    """
    start = Path(workspace).expanduser().resolve() if workspace is not None else Path.cwd()
    for folder in (start, *start.parents):
        if is_workspace_root(folder):
            return Workspace(folder)
    raise FileNotFoundError(
        f"No workspace at or above {start} (no workspace.toml, no projects/). "
        "Name it: hmp.index('<workspace root>')."
    )
