"""Write the reproducibility lockfile of a project from the sidecars of its data folder.

Who writes it
-------------
The launcher of a ``[sites]`` project writes ``hydromodpy.lock`` once, at
the end of the prepare phase, from the sidecars of the files every prepared
case fetched into the shared data folder
(:mod:`hydromodpy.project.launch.prepare`), plus the user files the
configurations declare. The workers then run ``--frozen`` against it. No run
rewrites it: a lockfile rewritten by every run was a writer of the cache in
every run. ``hmp data lock`` writes it by hand for a single project.

Why the file stays at the project root
--------------------------------------
The run manifest now carries the input provenance of each run: every file the
configuration declares is hashed at setup time and sealed into
``runs/<name>/manifest.json`` under ``inputs`` (path, SHA-256, size, origin).
That is what the run needs to say which DEM, which climate series and which
geometry produced its numbers, and it survives both an index loss and a move
to another machine inside the ``.hmp`` package.

``hydromodpy.lock`` is deliberately kept, because it answers a different
question and answers it *before* anything runs:

- Its scope is the **workspace data cache**, not one run: it freezes every
  sidecar row with its digest and licence, including files no run has
  consumed yet.
- It is the surface ``hmp run --frozen`` verifies before launching, and the
  reference ``hmp data lock --check`` compares the cache against. A manifest is
  written when a run ends, so it cannot gate one that has not started.
- It is an input-side artifact, the sibling of ``project.toml`` and
  ``configs/`` that a user commits next to them, exactly as ``poetry.lock``
  sits next to ``pyproject.toml``. Moving it under ``.hmp/`` would file a
  hand-readable reproducibility pin inside the internal area that
  ``hmp catalog reindex`` is free to rebuild.

So the project root keeps it, and the layout contract
(``tests/unit/results/test_run_layout_contract.py``) declares it instead of
tolerating it by accident. What the lockfile no longer has to carry is the
per-run input list: that duplication is gone.

One address, one resolver: every writer and every reader goes through
:func:`hydromodpy.data.provenance.lockfile.project_lockfile_path`, and frozen mode
carries the project root.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def write_project_lockfile(
    project_root: Path, data_dir: Path, *, quiet: bool = True
) -> Path | None:
    """Write ``hydromodpy.lock`` of *project_root* from the sidecars under *data_dir*.

    The lockfile pins every row of the data cache and every user file the
    project declares. Returns the lockfile path, or ``None`` when there is
    nothing to pin or the write fails (a data folder that still holds the
    database of a pre-release of 2.0 is refused by the scan, and is logged): the
    runs stay the source of truth.
    """
    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.config.user_files import user_file_inputs
    from hydromodpy.data.provenance.lockfile import (
        cache_inputs,
        project_lockfile_path,
        write_lockfile,
    )
    from hydromodpy.schema.config_schema import schema_sha256

    root = Path(project_root)
    dest = project_lockfile_path(root)
    try:
        user_files, refused = user_file_inputs(root)
        for path, reason in refused:
            logger.warning("%s is not locked: it does not load (%s).", path, reason)
        if not user_files and not cache_inputs(Path(data_dir)):
            return None
        write_lockfile(
            dest,
            Path(data_dir),
            user_files=user_files,
            schema_sha256=schema_sha256(ROOT_CONFIG.model),
            project_root=root,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort provenance, never fails the launch
        logger.warning("hydromodpy.lock write failed: %s", exc)
        return None
    if not quiet:
        logger.info("Lockfile written: %s", dest)
    return dest
