"""Project-scoped simulations namespace -- wraps ``catalog.duckdb``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.state.paths import CATALOG_FILENAME

if TYPE_CHECKING:
    import pandas as pd


class SimulationsNamespace:
    """Read-mostly facade over ``<project>/catalog.duckdb``.

    Lazily instantiates a :class:`~hydromodpy.results.catalog.SimulationCatalog`
    on first call so opening a facade against a workspace without a local
    catalog stays cheap and side-effect free.
    """

    def __init__(self, workspace: Path) -> None:
        self._workspace = Path(workspace).expanduser().resolve()
        self._catalog: Any = None

    def _open(self) -> Any:
        if self._catalog is None:
            from hydromodpy.results.catalog import SimulationCatalog

            self._catalog = SimulationCatalog(self._workspace)
        return self._catalog

    def has_catalog(self) -> bool:
        """Return ``True`` when ``<workspace>/catalog.duckdb`` exists on disk."""
        return (self._workspace / CATALOG_FILENAME).is_file()

    def find(self, **filters: Any) -> pd.DataFrame:
        """Return a DataFrame of simulations matching ``filters``.

        Equality filters map to columns of ``v_simulation_summary``
        (``solver``, ``status``, ``study_area_name``, ...). Unknown
        columns are silently ignored.
        """
        catalog = self._open()
        view = "v_simulation_summary"
        if not catalog.connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [view],
        ).fetchone()[0]:
            view = "simulations"
        available_cols = {
            row[0]
            for row in catalog.connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                [view],
            ).fetchall()
        }
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in filters.items():
            if column not in available_cols:
                continue
            clauses.append(f'"{column}" = ?')
            params.append(value)
        sql = f"SELECT * FROM {view}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return catalog.connection.execute(sql, params).fetchdf()

    def get(self, sim_id: str) -> pd.DataFrame:
        """Return one simulation row (empty DataFrame when ``sim_id`` is unknown)."""
        catalog = self._open()
        return catalog.connection.execute(
            "SELECT * FROM simulations WHERE sim_id = ?", [str(sim_id)]
        ).fetchdf()

    def list(self) -> pd.DataFrame:
        """Return every simulation registered in the project catalog."""
        return self.find()

    def close(self) -> None:
        if self._catalog is not None:
            self._catalog.close()
            self._catalog = None


__all__ = ["SimulationsNamespace"]
