"""Catalog constants and small solver helpers.

Hosts the Parquet view names, the SQL of the dimension joins and the metric helpers that read the direction table. The DDL of the index lives in
:mod:`hydromodpy.results.catalog.index_schema`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hydromodpy.core.exceptions import ResultsError
from hydromodpy.core.scoring.metric_table import METRIC_SENSE, MetricSense

if TYPE_CHECKING:
    import numpy as np

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
    "data_inventory",
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


RETIRED_METRIC_NAMES: dict[str, str] = {"log_nse": "nse_log"}
"""Metric names the catalog no longer knows, each with the name to write.

A query naming one is refused with the new name.
"""


class UnrankedMetricError(ResultsError, ValueError):
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


Value = TypeVar("Value", float, "np.ndarray")


def _flips(metric: str) -> bool:
    """Say whether ``metric`` rises with the fit, so its cost is one minus it.

    Refuses a metric best at a target (zero or one): it is no cost as it stands.
    """
    sense = metric_sense(metric)
    if sense in ("zero", "one"):
        raise UnrankedMetricError(
            f"Metric '{metric}' is best at {0 if sense == 'zero' else 1}, not at one end "
            "of its range: it has no cost to minimise."
        )
    return sense == "max"


def cost_of(metric: str, score: Value) -> Value:
    """Return the cost a search minimizes for a ``score`` of ``metric``.

    One minus the score for a metric that rises with the fit (an efficiency,
    perfect at 1); the score itself for one that falls (an error, a distance).
    A value or an array.
    """
    return 1.0 - score if _flips(metric) else score


def score_of(metric: str, cost: Value) -> Value:
    """Return the score of ``metric`` that a search ``cost`` stands for.

    The inverse of :func:`cost_of`.
    """
    return 1.0 - cost if _flips(metric) else cost


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


SIMULATIONS_FROM = (
    "FROM simulations s "
    "JOIN solvers sv ON s.solver_id = sv.id "
    "JOIN statuses st ON s.status_id = st.id "
    "LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id "
    "LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id"
)
"""The ``simulations`` table joined to the codes of its dimensions, as every reader of a row joins it."""


__all__ = [
    "SIMULATIONS_FROM",
    "MESH_ENGINE_SQL",
    "PARQUET_VIEW_NAMES",
    "RETIRED_METRIC_NAMES",
    "UnrankedMetricError",
    "cost_of",
    "metric_rank_sql",
    "metric_sense",
    "score_of",
]
