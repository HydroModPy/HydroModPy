"""Removal of the geographic preprocessing tree once the run holds what it needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def cleanup_intermediate_dirs(geographic: Any) -> None:
    import shutil

    for attr in ("geographic_path", "correcflow_path"):
        path = getattr(geographic, attr, None)
        if path is not None and Path(path).is_dir():
            shutil.rmtree(path, ignore_errors=True)
            logger.debug("Cleaned up intermediate dir %s", path)

    stable = getattr(geographic, "stable_folder", None)
    if stable is not None:
        stable_path = Path(stable)
        if stable_path.is_dir() and not any(stable_path.iterdir()):
            stable_path.rmdir()
            logger.debug("Removed empty stable folder %s", stable_path)


def cleanup_stable_folder(geographic: Any, *, keep: bool = False) -> int:
    """Drop the geographic preprocessing tree, returning the bytes freed.

    The tree (corrected DEM, D8 pointer and accumulation, watershed, stream
    network) is written once and then ingested into the project store, so it is
    a rebuildable cache rather than a result. It is shared by every consumer
    that skips the setup steps - a calibration session reuses it across its
    whole trial loop - so only the code that owns the END of a session may drop
    it. ``keep`` honours ``[geographic] write_intermediates``.
    """
    import shutil

    stable = getattr(geographic, "stable_folder", None)
    if keep or stable is None:
        return 0
    stable_path = Path(stable)
    if not stable_path.is_dir():
        return 0
    freed = _directory_size(stable_path)
    shutil.rmtree(stable_path, ignore_errors=True)
    logger.info(
        "Removed %s (%.0f MB freed) - all data is in the project store",
        stable_path,
        freed / 1e6,
    )
    _drop_empty_parents(stable_path)
    return freed


def _drop_empty_parents(stable_path: Path) -> None:
    """Remove the run's scratch folder, then ``.hmp/scratch/``, once they hold nothing.

    A ``Project`` drops its tree when it closes, after the run's own scratch
    scope ended, so the folder the tree sat in is left empty behind it.
    """
    parent = stable_path.parent
    targets = [parent] if parent.name == "scratch" else [parent, parent.parent]
    for target in targets:
        try:
            target.rmdir()
        except OSError:
            return


def _directory_size(root: Path) -> int:
    """Return the total size in bytes of the files under ``root``."""
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total
