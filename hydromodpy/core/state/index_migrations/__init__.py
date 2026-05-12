"""Machine-wide global index DuckDB schema migrations.

Thin wrapper that binds the generic migration runner from
``hydromodpy.core.migrations`` to the bundled SQL ``versions/`` directory and
to the ``"index"`` component name.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.migrations import ensure_schema as _ensure_schema

if TYPE_CHECKING:
    import duckdb

INDEX_COMPONENT = "index"

_VERSIONS_DIR = Path(__file__).resolve().parent / "versions"


def ensure_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """Bring the global index DuckDB schema up to the latest bundled version."""
    _ensure_schema(connection, versions_dir=_VERSIONS_DIR, component=INDEX_COMPONENT)


__all__ = ["INDEX_COMPONENT", "ensure_schema"]
