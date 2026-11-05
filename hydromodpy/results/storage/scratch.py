"""The solver scratch of an attempt: what leaves it at the end of a run, and how.

``attempt.scratch_dir_for_attempt`` says where the scratch is; this module
empties it. The rules read folders only, never the workflow context.
"""

from __future__ import annotations

import gc
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.state.paths import PREPROCESSING_DIRNAME, active_run_scratch

if TYPE_CHECKING:
    from collections.abc import Iterable

_SCRATCH_CLEANUP_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6)


def clear_scratch(
    scratch: Path,
    *,
    kept: Path | None = None,
    spare: Iterable[str | Path] = (),
) -> None:
    """Remove the children of ``scratch``, or move them into ``kept`` when it is given.

    Every child goes but the geographic ``_preprocessing/`` tree, which belongs
    to the session. ``spare`` names folders someone else still owns (the solver
    folders of the calibration trials a session keeps for their own promotion):
    a child holding one of them stays. A move replaces a former copy.
    """
    if not scratch.exists():
        return
    spared = {Path(folder).resolve() for folder in spare}
    for target in sorted(scratch.iterdir()):
        if target.name == PREPROCESSING_DIRNAME:
            continue
        resolved = target.resolve()
        if any(folder == resolved or resolved in folder.parents for folder in spared):
            continue
        if kept is None:
            _remove_scratch_path(target)
        else:
            _keep_scratch_path(target, kept)


def _keep_scratch_path(target: Path, kept: Path) -> None:
    """Move one scratch entry into the solver folder of the run, replacing a former copy."""
    destination = kept / target.name
    if destination.is_dir():
        shutil.rmtree(destination)
    elif destination.exists():
        destination.unlink()
    kept.mkdir(parents=True, exist_ok=True)
    shutil.move(target, destination)


def _remove_scratch_path(target: Path) -> None:
    """Delete one scratch entry, retrying while a handle still pins it."""
    release_cleanup_handles()
    last_error: OSError | None = None
    for delay in (0.0, *_SCRATCH_CLEANUP_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
            release_cleanup_handles()
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
    raise ExportError(
        f"Could not remove solver scratch directory: {target}: {last_error}"
    ) from last_error


def drop_empty_scratch(folder: Path) -> None:
    """Remove the scratch folder of a run, then ``.hmp/scratch/``, once nothing is left under them."""
    folder = Path(folder)
    for target in (folder, folder.parent) if active_run_scratch() else (folder,):
        try:
            target.rmdir()
        except OSError:
            # Still holding the preprocessing tree, a solver folder or another
            # run's folder: not ours to force.
            return


def release_cleanup_handles() -> None:
    """Release best-effort runtime handles before deleting scratch files.

    No catalog handle survives the step that opened it, so the Zarr handles a
    catalog tracked are already closed by the time the scratch goes. A garbage
    collection drops what is left unreferenced.
    """
    gc.collect()
