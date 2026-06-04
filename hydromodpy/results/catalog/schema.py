"""Self-documenting schema accessors for :class:`SimulationCatalog`.

Mixed into the catalog facade so callers can discover what to query without
reading the DDL: ``describe`` (human summary), ``tables``, ``columns``,
``variables`` (Zarr fields + timeseries + features), ``metrics``, ``stations``.
"""

from __future__ import annotations

from typing import Any


class SchemaDiscoveryMixin:
    """Schema-introspection methods for :class:`SimulationCatalog`.

    Relies on the facade attribute ``self._backend`` (CatalogBackend port).
    """

    def tables(self) -> list[str]:
        """Tables and views available to :meth:`sql`."""
        rows = self._backend.fetch_all(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        return [str(r[0]) for r in rows]

    def columns(self, table: str = "simulations") -> list[str]:
        """Column names of ``table``."""
        rows = self._backend.fetch_all(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        )
        return [str(r[0]) for r in rows]

    def variables(self) -> list[str]:
        """Readable variable names (Zarr fields + timeseries + features)."""
        from hydromodpy.results import field_registry

        names: set[str] = set(field_registry.all_names())
        for sql in (
            "SELECT DISTINCT variable FROM timeseries",
            "SELECT DISTINCT feature_name FROM geographic_features",
        ):
            try:
                names.update(str(r[0]) for r in self._backend.fetch_all(sql))
            except Exception:
                continue
        return sorted(names)

    def metrics(self) -> list[str]:
        """Distinct metric names recorded in the catalog."""
        try:
            rows = self._backend.fetch_all(
                "SELECT DISTINCT metric_name FROM metrics ORDER BY metric_name"
            )
        except Exception:
            return []
        return [str(r[0]) for r in rows]

    def stations(self) -> list[str]:
        """Distinct station ids referenced by metrics or timeseries."""
        names: set[str] = set()
        for sql in (
            "SELECT DISTINCT station_id FROM metrics WHERE station_id IS NOT NULL",
            "SELECT DISTINCT station_id FROM timeseries WHERE station_id IS NOT NULL",
        ):
            try:
                names.update(str(r[0]) for r in self._backend.fetch_all(sql))
            except Exception:
                continue
        return sorted(names)

    def describe(self) -> str:
        """Return a human-readable summary of the catalog content."""

        def scalar(sql: str) -> Any:
            try:
                row = self._backend.fetch_one(sql)
            except Exception:
                return None
            return row[0] if row else None

        def distinct(sql: str) -> list[str]:
            try:
                return [str(r[0]) for r in self._backend.fetch_all(sql) if r[0] is not None]
            except Exception:
                return []

        total = scalar("SELECT COUNT(*) FROM simulations") or 0
        completed = (
            scalar(
                "SELECT COUNT(*) FROM simulations s JOIN statuses st "
                "ON s.status_id = st.id WHERE st.code = 'completed'"
            )
            or 0
        )
        failed = (
            scalar(
                "SELECT COUNT(*) FROM simulations s JOIN statuses st "
                "ON s.status_id = st.id WHERE st.code = 'failed'"
            )
            or 0
        )
        projects = distinct("SELECT DISTINCT project FROM simulations ORDER BY project")
        solvers = distinct("SELECT DISTINCT code FROM solvers")

        def fmt(items: list[str], limit: int = 12) -> str:
            if not items:
                return "-"
            head = ", ".join(items[:limit])
            return head + (f", ... (+{len(items) - limit})" if len(items) > limit else "")

        return "\n".join(
            [
                f"Catalog {self._workspace}",
                f"  simulations : {total} ({completed} completed, {failed} failed)",
                f"  projects    : {fmt(projects)}",
                f"  solvers     : {fmt(solvers)}",
                f"  metrics     : {fmt(self.metrics())}",
                f"  stations    : {fmt(self.stations())}",
            ]
        )


__all__ = ["SchemaDiscoveryMixin"]
