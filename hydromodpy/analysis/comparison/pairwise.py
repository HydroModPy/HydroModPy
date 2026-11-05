"""Pairwise simulation comparison via DuckDB SQL pivot."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.metric_rule import HEADLINE_WINDOW


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

    One row per (metric, station, variable) carries the score of each simulation
    (``A`` for ``sim_a``, ``B`` for ``sim_b``), the window it was scored on
    (``A_window``, as ``start/end``) and its samples (``A_n``). When the catalog
    holds no metrics for either reference, an empty DataFrame is returned.

    ``workspace`` defaults to the nearest ancestor of ``cwd`` holding a
    project index database.
    """
    start = Path(workspace).expanduser().resolve() if workspace is not None else Path.cwd()
    workspace_root = _discover_catalog_root(start)
    if not (catalog_path_for(workspace_root)).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with Catalog(workspace_root) as catalog:
        sid_a = catalog.resolve(sim_a)
        sid_b = catalog.resolve(sim_b)
        df = catalog.sql(
            "SELECT sim_id, station_id, variable, metric_name, value, "
            "window_start, window_end, n_samples "
            "FROM metrics WHERE sim_id IN (?, ?) AND window_name = ? "
            "ORDER BY metric_name, station_id, variable",
            [sid_a, sid_b, HEADLINE_WINDOW],
        )

    if df.empty:
        return df

    keys = ["metric_name", "station_id", "variable"]
    df["window"] = [
        None
        if pd.isna(start)
        else f"{pd.Timestamp(start).date().isoformat()}/{pd.Timestamp(end).date().isoformat()}"
        for start, end in zip(df["window_start"], df["window_end"], strict=True)
    ]
    sides = []
    for label, sid in (("A", sid_a), ("B", sid_b)):
        side = df[df["sim_id"].astype(str) == str(sid)].drop_duplicates(keys).set_index(keys)
        sides.append(
            side[["value", "window", "n_samples"]].rename(
                columns={"value": label, "window": f"{label}_window", "n_samples": f"{label}_n"}
            )
        )
    return sides[0].join(sides[1], how="outer").sort_index()


__all__ = ("compare_pair",)
