"""Catalog constants and small solver helpers.

Hosts string sentinels reused across the catalog write path (``GLOBAL_ZONE``,
``OUTLET_STATION``), the canonical table-name lists, and the solver
category resolver. The DDL itself lives in the SQL migration scripts under
``catalog/migrations/versions/``.
"""

from __future__ import annotations

GLOBAL_ZONE = "__global__"
"""Sentinel parameter zone used when no spatial zoning applies."""

OUTLET_STATION = "__outlet__"
"""Sentinel station id for the catchment outlet."""

# v2 catalog table names (DuckDB). Kept in sync with
# ``catalog/migrations/versions/0001_initial_v2_schema.sql``.
TABLE_NAMES: tuple[str, ...] = (
    "_schema_version",
    "schema_migrations",
    "solvers",
    "statuses",
    "flow_regimes",
    "mesh_topologies",
    "dim_variables",
    "dim_stations",
    "dim_metrics",
    "dim_projects",
    "dim_study_areas",
    "stations",
    "simulations",
    "parameters",
    "metrics",
    "metric_definitions",
    "runs_environment",
    "provenance",
    "observations",
    "observation_points",
    "audit_log",
    "deletions",
    "tracked_files",
    "geographic_features",
    "geographic_metadata",
    "parquet_files",
    "tags",
    "calibration_sessions",
    "calibration_iterations",
    "workflow_steps",
)

# Per-simulation DuckDB tables (used by lifecycle deletion and hmp_package).
PER_SIM_TABLE_NAMES: tuple[str, ...] = (
    "parameters",
    "metrics",
    "observation_points",
    "provenance",
    "geographic_features",
    "geographic_metadata",
    "runs_environment",
    "tags",
    "tracked_files",
    "parquet_files",
)

# Per-simulation Parquet view aliases. Files live at
# ``simulations/<basename>.parquet/<view>.parquet`` in the workspace.
# Includes ``metrics`` and ``provenance``: in v2 these are no longer orphan
# Parquet files but proper DuckDB-backed views.
PARQUET_VIEW_NAMES: tuple[str, ...] = (
    "timeseries",
    "budgets",
    "mass_balance",
    "metrics",
    "provenance",
)


def solver_category(solver_name: str) -> str | None:
    """Return the category for in-tree solvers without importing solver layers."""
    known = {
        "boussinesq": "integrated",
        "gr4j": "lumped",
        "modflow6": "distributed",
        "modflow6gwt": "distributed",
        "modflownwt": "distributed",
        "modpath": "distributed",
        "mt3dms": "distributed",
    }
    parts = [part.strip() for part in str(solver_name).split(",") if part.strip()]
    if not parts:
        return None
    categories = {known[part] for part in parts if part in known}
    if len(categories) == 1 and len(categories) == len(parts):
        return categories.pop()
    return None


# Map free-form solver names (legacy v1 vocabulary) to v2 ``solvers.code``.
# Used by the registration / discovery layers when bridging callers that still
# pass solver names as strings, before P5 introduces a typed enum end-to-end.
_LEGACY_SOLVER_CODE_MAP: dict[str, str] = {
    "modflow6": "modflow6",
    "modflow6gwt": "modflow6",
    "modflow_nwt": "modflow_nwt",
    "modflownwt": "modflow_nwt",
    "boussinesq": "boussinesq",
    "gr4j": "gr4j",
    "mt3dms": "mt3dms",
    "modpath": "modpath",
}


def solver_code(solver_name: str) -> str:
    """Normalise a legacy solver name to its v2 ``solvers.code`` value."""
    key = str(solver_name).strip().lower()
    return _LEGACY_SOLVER_CODE_MAP.get(key, key)


__all__ = [
    "GLOBAL_ZONE",
    "OUTLET_STATION",
    "PARQUET_VIEW_NAMES",
    "PER_SIM_TABLE_NAMES",
    "TABLE_NAMES",
    "solver_category",
    "solver_code",
]
