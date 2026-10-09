"""Catalog constants and small solver helpers.

Hosts string sentinels reused across the catalog write path (``GLOBAL_ZONE``,
``OUTLET_STATION``), the canonical table-name lists, and the solver
category resolver. The DDL itself lives in the SQL migration scripts under
``catalog/migrations/``.
"""

from __future__ import annotations

GLOBAL_ZONE = "__global__"
"""Sentinel parameter zone used when no spatial zoning applies."""

OUTLET_STATION = "__outlet__"
"""Sentinel station id for the catchment outlet."""

TRASH_RETENTION_DAYS = 30
"""Days a trashed run stays restorable before ``gc --apply`` may hard-purge it."""

STALE_HEARTBEAT_MINUTES = 10
"""Minutes without a heartbeat before a ``running`` sim is treated as stale."""

# v2 catalog table names (DuckDB). Kept in sync with
# ``catalog/migrations/0001_initial.sql``.
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
    "audit_log",
    "deletions",
    "tracked_files",
    "geographic_features",
    "geographic_metadata",
    "tags",
    "sim_notes",
    "export_log",
    "purge_journal",
    "calibration_sessions",
    "calibration_iterations",
    "workflow_steps",
)

# Per-simulation DuckDB tables (used by lifecycle deletion and hmp_package).
# ``purge_journal`` is deliberately excluded: it is the two-phase hard-purge
# journal cleared by the purge process itself, not part of the normal cascade.
PER_SIM_TABLE_NAMES: tuple[str, ...] = (
    "parameters",
    "metrics",
    "provenance",
    "geographic_features",
    "geographic_metadata",
    "runs_environment",
    "tags",
    "sim_notes",
    "export_log",
    "tracked_files",
)

# Per-simulation Parquet view aliases. Files live at
# ``runs/<run>/tables.parquet/<view>.parquet`` in the project.
# Includes ``metrics`` and ``provenance``: in v2 these are no longer orphan
# Parquet files but proper DuckDB-backed views.
PARQUET_VIEW_NAMES: tuple[str, ...] = (
    "timeseries",
    "budgets",
    "mass_balance",
    "metrics",
    "provenance",
    "observation_points",
    "sfr_reaches",
    "soil_budget",
)


# Canonical v2 solver codes, mirroring ``solvers.code`` rows in
# ``catalog/migrations/0001_initial.sql``.
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

# Short aliases users may type on the CLI mapped to canonical solver codes.
SOLVER_ALIASES: dict[str, str] = {
    "mf6": "modflow6",
    "nwt": "modflow_nwt",
}


def canonical_solver_code(name: str) -> str:
    """Return the canonical solver code for a user-typed name or alias."""
    key = str(name).strip().lower()
    return SOLVER_ALIASES.get(key, key)


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


# Which value of a metric is the good one. The single table of metric
# directions: ``@best:<metric>``, ``Catalog.best``, ``RunSet.best``,
# ``hmp dev rank`` and the calibration criteria read it, so "best" means the
# best fit whatever the metric, and a score becomes a cost the same way
# everywhere.
# The seeded ``metric_definitions`` rows of the catalog agree with it
# (``higher_is_better`` TRUE is "max", FALSE is "min", NULL is "zero").
#
# - ``max``: a higher value is better (efficiency scores).
# - ``min``: a lower value is better (errors, costs).
# - ``zero``: the value closest to zero is better (signed biases).
# - ``one``: the value closest to one is better (KGE ratios).
METRIC_SENSE: dict[str, str] = {
    "nse": "max",
    "log_nse": "max",
    "nse_log": "max",
    "nse_delta": "max",
    "nse_seasonal": "max",
    "kge": "max",
    "kge_delta": "max",
    "kge_r": "max",
    "r2": "max",
    "correlation": "max",
    "reservoir": "max",
    "rmse": "min",
    "mae": "min",
    "mse": "min",
    "objective_best": "min",
    "closure_max_abs_m3_s": "min",
    "closure_mean_abs_m3_s": "min",
    "closure_rmse_m3_s": "min",
    "closure_max_abs_mm_d": "min",
    "closure_relative_error_p95": "min",
    "distance_gap": "min",
    "distance_mean": "min",
    "bias": "zero",
    "pbias": "zero",
    "kge_alpha": "one",
    "kge_beta": "one",
}
"""Direction of every metric the catalog knows how to rank."""


class UnrankedMetricError(ValueError):
    """Raised when a metric has no declared direction, so best is undefined."""


def metric_rank_sql(metric: str, *, best: bool, column: str = "m.value") -> str:
    """Return the ``ORDER BY`` expression that puts the best (or worst) value first.

    Raises :class:`UnrankedMetricError` for a metric missing from
    :data:`METRIC_SENSE`: taking the highest value of an error would hand back
    the worst run under the name of the best one.
    """
    sense = METRIC_SENSE.get(str(metric).strip().lower())
    if sense is None:
        known = ", ".join(sorted(METRIC_SENSE))
        raise UnrankedMetricError(
            f"Metric '{metric}' has no declared direction, so best and worst are "
            f"undefined for it. Metrics with a direction: {known}."
        )
    if sense == "max":
        return f"{column} {'DESC' if best else 'ASC'}"
    if sense == "min":
        return f"{column} {'ASC' if best else 'DESC'}"
    target = "0" if sense == "zero" else "1"
    return f"ABS({column} - {target}) {'ASC' if best else 'DESC'}"


__all__ = [
    "GLOBAL_ZONE",
    "METRIC_SENSE",
    "OUTLET_STATION",
    "PARQUET_VIEW_NAMES",
    "PER_SIM_TABLE_NAMES",
    "SOLVER_ALIASES",
    "STALE_HEARTBEAT_MINUTES",
    "TABLE_NAMES",
    "TRASH_RETENTION_DAYS",
    "UnrankedMetricError",
    "VALID_SOLVER_CODES",
    "canonical_solver_code",
    "metric_rank_sql",
    "solver_category",
    "validate_solver_code",
]
