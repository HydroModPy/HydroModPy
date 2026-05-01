"""Pairwise simulation comparison via DuckDB SQL pivot."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.results.catalog import SimulationCatalog


def _discover_workspace_root(start: Path) -> Path:
    """Walk up from ``start`` to find ``hydromodpy.duckdb``."""
    for parent in [start, *start.parents]:
        if (parent / "hydromodpy.duckdb").exists():
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

    ``workspace`` defaults to the nearest ancestor of ``cwd`` containing
    ``hydromodpy.duckdb``.
    """
    start = Path(workspace).expanduser().resolve() if workspace is not None else Path.cwd()
    workspace_root = _discover_workspace_root(start)
    if not (workspace_root / "hydromodpy.duckdb").exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with SimulationCatalog(workspace_root) as catalog:
        sid_a = catalog.resolve(sim_a)
        sid_b = catalog.resolve(sim_b)
        df = catalog.sql(
            "SELECT sim_id, station_id, metric_name, value "
            "FROM metrics WHERE sim_id IN (?, ?) "
            "ORDER BY metric_name, station_id",
            [sid_a, sid_b],
        ).fetchdf()

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
