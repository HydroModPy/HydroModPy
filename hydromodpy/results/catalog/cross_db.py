"""Cross-DB helper federating the project catalog with the data cache.

:func:`run_input_entries` lists the cache entries a sim_id referenced
through the ``tracked_files`` table, joined on ``sha256``. It relies on a
strictly read-only DuckDB ``ATTACH``: the cache database is opened,
queried, and detached for every call. The invariant
"three DuckDB scopes, never physically merged" stays intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
    from hydromodpy.results.catalog.facade import Catalog


_CACHE_DB_FILENAME = "cache.duckdb"


def resolve_cache_db_path(catalog: Catalog) -> Path | None:
    """Return the path of the workspace cache DB next to ``catalog``.

    The canonical layout is ``<workspace>/data/cache.duckdb`` next to the
    project catalog. We walk upward from the catalog file looking for
    that layout; the search stays cheap (max 6 levels) and falls back to
    ``None`` so callers can decide whether to skip the cross-DB step.
    """
    workspace = catalog.workspace_path
    candidates = (
        workspace / "data" / _CACHE_DB_FILENAME,
        workspace.parent / "data" / _CACHE_DB_FILENAME,
        workspace.parent.parent / "data" / _CACHE_DB_FILENAME,
    )
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def run_input_entries(catalog: Catalog, sim_id: str) -> pd.DataFrame:
    """Return cache entries consumed by ``sim_id`` via the SHA-256 bridge.

    Empty result when the workspace cache DB cannot be located or when
    no tracked file matches an entry by SHA-256.
    """
    import pandas as pd

    cache_path = resolve_cache_db_path(catalog)
    if cache_path is None:
        return pd.DataFrame()

    backend: DuckDBBackend = catalog.backend  # type: ignore[assignment]
    sql = (
        "SELECT DISTINCT e.* "
        "FROM tracked_files tf "
        "JOIN cache_db.entries e ON tf.sha256 = e.sha256 "
        "WHERE tf.sim_id = ?"
    )
    with backend.attach_read_only(cache_path, "cache_db"):
        return backend.query(sql, [sim_id])


def _resolve_columns(row: tuple[Any, ...], cols: tuple[str, ...]) -> dict[str, Any]:
    """Pair tuple rows with their column names (utility used by callers)."""
    return dict(zip(cols, row, strict=False))


__all__ = ["resolve_cache_db_path", "run_input_entries"]
