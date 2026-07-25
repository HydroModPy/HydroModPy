"""Pairwise simulation comparison via DuckDB SQL pivot."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog import Catalog


def _discover_catalog_root(start: Path) -> Path:
    """Walk up from ``start`` to find a project catalog."""
    for parent in [start, *start.parents]:
        if (catalog_path_for(parent)).exists():
            return parent
    return start


def compare_pair(
    sim_a: str,
    sim_b: str,
    *,
    workspace: str | Path | None = None,
) -> pd.DataFrame:
    """Compare two simulations and return their metrics side-by-side.

    Pivots the ``metrics`` table so each metric/station row carries one column
    per simulation (``A`` for ``sim_a``, ``B`` for ``sim_b``). When the catalog
    holds no metrics for either reference, an empty DataFrame is returned.

    ``workspace`` defaults to the nearest ancestor of ``cwd`` holding a
    project index database.
    """
    start = Path(workspace).expanduser().resolve() if workspace is not None else Path.cwd()
    workspace_root = _discover_catalog_root(start)
    if not (catalog_path_for(workspace_root)).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with Catalog(workspace_root, read_only=True) as catalog:
        sid_a = catalog.resolve(sim_a)
        sid_b = catalog.resolve(sim_b)
        df = catalog.sql(
            "SELECT sim_id, station_id, metric_name, value "
            "FROM metrics WHERE sim_id IN (?, ?) "
            "ORDER BY metric_name, station_id",
            [sid_a, sid_b],
        )

    if df.empty:
        return df

    pivot = df.pivot_table(
        index=["metric_name", "station_id"],
        columns="sim_id",
        values="value",
        aggfunc="first",
    )
    return pivot.rename(columns={sid_a: "A", sid_b: "B"})


__all__ = ("compare_pair",)
