"""Scratch cleanup helper used by per-adapter ``cleanup(ctx)`` implementations.

Adapters call :func:`cleanup_solver_files` from their ``cleanup`` method.
The runner orchestrates the call once extraction has completed and the
results-config ``keep_solver_files`` flag allows it.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def cleanup_solver_files(
    solver_output_dir: Path,
    keep: set[str] | None = None,
) -> None:
    """Remove solver working files, optionally keeping some extensions.

    Parameters
    ----------
    solver_output_dir : Path
        Directory containing raw solver files.
    keep : set[str], optional
        File extensions to keep (e.g. ``{".lst", ".nam"}``).
        If ``None``, the entire directory is removed.
    """
    if keep is None:
        shutil.rmtree(solver_output_dir, ignore_errors=True)
        return

    for f in solver_output_dir.iterdir():
        if f.is_file() and f.suffix not in keep:
            f.unlink(missing_ok=True)
    for d in solver_output_dir.iterdir():
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


__all__ = ["cleanup_solver_files"]
