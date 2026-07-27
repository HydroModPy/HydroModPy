"""Write the reproducibility lockfile from a resolved config.

The CLI writes ``hydromodpy.lock`` after ``hmp run`` (see
``cli/commands/run.py``). This helper mirrors that write from a resolved
:class:`~hydromodpy.config.HydroModPyConfig`, so a Python-driven run
(``hmp.run`` / :class:`~hydromodpy.project.Project`) records the same
reproducibility provenance instead of silently skipping it.

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
  reference ``hmp dev lock verify`` compares the cache against. A manifest is
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
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.config import HydroModPyConfig

logger = get_logger(__name__)


def write_project_lockfile(config: HydroModPyConfig, *, quiet: bool = True) -> Path | None:
    """Write ``hydromodpy.lock`` next to the project from a resolved config.

    Best-effort: returns the lockfile path on success, or ``None`` when no
    workspace data cache exists yet or the write fails (the run output stays
    the source of truth). The solver-binary section is left empty; the value
    is the data provenance plus the storage-schema versions.
    """
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.data_freeze import LOCKFILE_NAME, write_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
    from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION

    project_root = Path(config.workspace.project_root)
    db_path = Path(config.workspace.data_dir) / "cache.duckdb"
    if not db_path.is_file():
        return None

    dest = project_root / LOCKFILE_NAME
    try:
        with DataCatalogDuckDB(db_path) as catalog:
            write_lockfile(
                catalog,
                dest,
                project_root=project_root,
                solvers={},
                schema_sha256=schema_sha256(),
                zarr_schema_version=str(ZARR_SCHEMA_VERSION),
                parquet_schema_version=str(PARQUET_SCHEMA_VERSION),
            )
    except Exception as exc:  # best-effort provenance, never fails the run
        logger.warning("hydromodpy.lock write failed: %s", exc)
        return None
    if not quiet:
        logger.info("Lockfile written: %s", dest)
    return dest
