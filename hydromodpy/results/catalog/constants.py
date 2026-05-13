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


# Canonical v2 solver codes, mirroring ``solvers.code`` rows in
# ``catalog/migrations/versions/0001_initial_v2_schema.sql``.
VALID_SOLVER_CODES: frozenset[str] = frozenset(
    {
        "boussinesq",
        "gr4j",
        "modflow6",
        "modflow_nwt",
        "modpath",
        "mt3dms",
    }
)


def solver_category(solver_name: str) -> str | None:
    """Return the category for in-tree solvers without importing solver layers."""
    known = {
        "boussinesq": "integrated",
        "gr4j": "lumped",
        "modflow6": "distributed",
        "modflow_nwt": "distributed",
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


def validate_solver_code(solver_name: str) -> str:
    """Validate a solver code against the canonical v2 vocabulary.

    Returns the trimmed lower-case code on success.

    Raises
    ------
    ValueError
        When *solver_name* is not a known ``solvers.code`` value.
    """
    key = str(solver_name).strip().lower()
    if key not in VALID_SOLVER_CODES:
        known = ", ".join(sorted(VALID_SOLVER_CODES))
        raise ValueError(f"Unknown solver code {solver_name!r}. Expected one of: {known}.")
    return key


__all__ = [
    "GLOBAL_ZONE",
    "OUTLET_STATION",
    "PARQUET_VIEW_NAMES",
    "PER_SIM_TABLE_NAMES",
    "TABLE_NAMES",
    "VALID_SOLVER_CODES",
    "solver_category",
    "validate_solver_code",
]
