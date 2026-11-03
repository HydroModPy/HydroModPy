"""Write the reproducibility lockfile of a project from the workspace data cache.

Who writes it
-------------
The launcher of a ``[sites]`` project writes ``hydromodpy.lock`` once, at
the end of the prepare phase, from the shared cache every prepared case
filled (:mod:`hydromodpy.project.launch.prepare`). The workers then run
``--frozen`` against it. No run rewrites it: a lockfile rewritten by every
run was a writer of the cache in every run. ``hmp lock`` writes it by
hand for a single project.

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
  catalog entry with its digest, including files no run has consumed yet.
- It is the surface ``hmp run --frozen`` verifies before launching, and the
  reference ``hmp lock verify`` compares the cache against. A manifest is
  written when a run ends, so it cannot gate one that has not started.
- It is an input-side artefact, the sibling of ``project.toml`` and
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
carries the project root instead of guessing it from the cache database.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import data_cache_path_for

logger = get_logger(__name__)


def write_project_lockfile(
    project_root: Path, data_dir: Path, *, quiet: bool = True
) -> Path | None:
    """Write ``hydromodpy.lock`` of *project_root* from the cache under *data_dir*.

    The cache is opened read-only. Returns the lockfile path, or ``None``
    when the workspace has no data cache yet or the write fails: the runs
    stay the source of truth. The solver-binary section is left empty; the
    value is the data provenance plus the storage-schema versions.
    """
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.provenance.lockfile import project_lockfile_path
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.registry.freeze import write_lockfile
    from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
    from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION

    root = Path(project_root)
    db_path = data_cache_path_for(Path(data_dir))
    if not db_path.is_file():
        return None

    dest = project_lockfile_path(root)
    try:
        with DataCatalogDuckDB(db_path, read_only=True) as catalog:
            write_lockfile(
                catalog,
                dest,
                project_root=root,
                solvers={},
                schema_sha256=schema_sha256(),
                zarr_schema_version=str(ZARR_SCHEMA_VERSION),
                parquet_schema_version=str(PARQUET_SCHEMA_VERSION),
            )
    except Exception as exc:  # noqa: BLE001 - best-effort provenance, never fails the launch
        logger.warning("hydromodpy.lock write failed: %s", exc)
        return None
    if not quiet:
        logger.info("Lockfile written: %s", dest)
    return dest
