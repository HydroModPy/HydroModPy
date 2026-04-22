"""Protocol for output adapters that ingest solver files into a store."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Protocol


class OutputAdapter(Protocol):
    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
    ) -> None: ...

    def derive(
        self,
        sim_id: str,
        store: Any,
        config: dict | None = None,
    ) -> None: ...


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
