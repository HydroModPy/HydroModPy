"""Catalog constants and small solver helpers.

Hosts the string sentinel of the stored tables (``GLOBAL_ZONE``), the
Parquet view names, the solver vocabulary and the direction of every metric. The DDL of the index lives in
:mod:`hydromodpy.results.catalog.index_schema`.
"""

from __future__ import annotations

from typing import Literal

GLOBAL_ZONE = "__global__"
"""Sentinel parameter zone used when no spatial zoning applies."""

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
    "mesh_cell_families",
    "mesh_face_families",
)


MESH_ENGINE_SQL: str = "s.mesh_engine"
"""SQL expression of the ``mesh_engine`` column of a run: the engine its seal names.

The indexer copies ``geometry.mesh_engine`` of ``manifest.json`` into the
column, so a run whose configuration has no ``[mesh]`` section shows the
default engine it ran on. The expression reads the ``simulations`` table
under the alias ``s``.
"""


# Canonical solver codes, the ``solvers.code`` rows of the index schema.
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
#
# - ``max``: a higher value is better (efficiency scores).
# - ``min``: a lower value is better (errors, costs).
# - ``zero``: the value closest to zero is better (signed biases).
# - ``one``: the value closest to one is better (KGE ratios).
MetricSense = Literal["max", "min", "zero", "one"]
"""Which value of a metric is the good one."""

METRIC_SENSE: dict[str, MetricSense] = {
    "nse": "max",
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


RETIRED_METRIC_NAMES: dict[str, str] = {"log_nse": "nse_log"}
"""Metric names the catalog no longer knows, each with the name to write.

A query naming one is refused with the new name.
"""


class UnrankedMetricError(ValueError):
    """Raised when a metric has no declared direction, so best is undefined."""


def metric_sense(metric: str) -> MetricSense:
    """Return the direction of ``metric`` from :data:`METRIC_SENSE`.

    Raises :class:`UnrankedMetricError` for a retired name, with the name to
    write, and for a metric without a declared direction: taking the highest
    value of an error would hand back the worst run under the name of the best.
    """
    key = str(metric).strip().lower()
    if key in RETIRED_METRIC_NAMES:
        raise UnrankedMetricError(
            f"Metric '{metric}' was renamed: write '{RETIRED_METRIC_NAMES[key]}'."
        )
    sense = METRIC_SENSE.get(key)
    if sense is None:
        known = ", ".join(sorted(METRIC_SENSE))
        raise UnrankedMetricError(
            f"Metric '{metric}' has no declared direction, so best and worst are "
            f"undefined for it. Metrics with a direction: {known}."
        )
    return sense


def metric_rank_sql(metric: str, *, best: bool, column: str = "m.value") -> str:
    """Return the ``ORDER BY`` expression that puts the best (or worst) value first.

    The direction is :func:`metric_sense`, which refuses a metric without one.
    """
    sense = metric_sense(metric)
    if sense == "max":
        return f"{column} {'DESC' if best else 'ASC'}"
    if sense == "min":
        return f"{column} {'ASC' if best else 'DESC'}"
    target = "0" if sense == "zero" else "1"
    return f"ABS({column} - {target}) {'ASC' if best else 'DESC'}"


__all__ = [
    "GLOBAL_ZONE",
    "METRIC_SENSE",
    "MESH_ENGINE_SQL",
    "PARQUET_VIEW_NAMES",
    "RETIRED_METRIC_NAMES",
    "SOLVER_ALIASES",
    "MetricSense",
    "UnrankedMetricError",
    "VALID_SOLVER_CODES",
    "canonical_solver_code",
    "metric_rank_sql",
    "metric_sense",
    "solver_category",
    "validate_solver_code",
]
