"""The summary views of the index, written by the indexer next to its tables.

``v_cases`` is the view a project of N cases is read through: one row per
result directory, the sealed facts of the run when it has a seal, its label,
the headline metric under its rule and one column per global parameter the
index holds, so ``arg_max(K, nse)`` answers over a site. The parameter
columns are read from ``parameters`` when the view is written: a parameter
whose name is not a plain identifier, or collides with a fixed column, stays
in ``v_params_long`` only. ``v_simulation_summary`` is the same projection
for sealed runs only. ``v_best_per_project`` holds the best scored run of each
project under each rule (gauge, variable, window, rule version): two scores
compete only under one rule, so a project scored on two windows has two rows.
``v_metrics_wide`` pivots the stored metrics on the names of the run kernels,
one row per run, station and variable; ``v_params_long`` and
``v_params_keyed`` expose every parameter, zoned ones included.

The DDL stays in a Postgres-compatible subset: no ``PIVOT``, no ``MAP``, no
``QUALIFY``. The views carry no file path, so they live in the index file
itself; the Parquet-backed views of the payloads are installed per connection
by :mod:`hydromodpy.results.catalog.parquet_views`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.scoring.metric_table import RUN_METRIC_NAMES
from hydromodpy.results.catalog.constants import MESH_ENGINE_SQL
from hydromodpy.results.metric_rule import HEADLINE_WINDOW

if TYPE_CHECKING:
    import duckdb

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _wide_metric_columns() -> str:
    """One column per metric the run kernels compute: ``MAX(CASE WHEN ...)`` needs the list."""
    lines = []
    for name in RUN_METRIC_NAMES:
        safe = name.replace("'", "''")
        lines.append(f"    MAX(CASE WHEN metric = '{safe}' THEN value END) AS {name}")
    return ",\n".join(lines)


_V_SIMULATION_SUMMARY_DDL = f"""
CREATE OR REPLACE VIEW v_simulation_summary AS
SELECT
    s.sim_id,
    s.name,
    s.project,
    s.site,
    s.site_fingerprint,
    s.recipe,
    s.case_id,
    s.rel_dir,
    s.attempt,
    s.attempt_id,
    st.code AS status,
    sv.code AS solver,
    sv.category AS solver_category,
    fr.code AS flow_regime,
    mt.code AS mesh_topology,
    {MESH_ENGINE_SQL} AS mesh_engine,
    s.mesh_hash,
    s.solution_key,
    s.request_id,
    s.hydromodpy_version,
    s.scientific_objective,
    s.description,
    s.contact_email,
    s.bbox_xmin,
    s.bbox_ymin,
    s.bbox_xmax,
    s.bbox_ymax,
    s.period_start,
    s.period_end,
    s.created_at,
    s.duration_s,
    s.label,
    s.label_date,
    s.rule_version,
    s.nse,
    s.score_station,
    s.score_variable,
    s.score_window_start,
    s.score_window_end,
    s.n_samples,
    s.metric_rule_version,
    s.calibrated_by_metric,
    s.calibrated_by_cost,
    s.calibrated_by_window_start,
    s.calibrated_by_window_end,
    s.budget_pct,
    s.converged,
    s.calibrated_by_session_id
FROM simulations s
JOIN solvers sv ON s.solver_id = sv.id
JOIN statuses st ON s.status_id = st.id
LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id
LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id
"""

_CASE_COLUMNS: tuple[str, ...] = (
    "rel_dir",
    "kind",
    "case_id",
    "site",
    "recipe",
    "project",
    "sim_id",
    "attempt",
    "attempt_id",
    "status",
    "started_at",
    "ended_at",
    "heartbeat_at",
    "host",
    "step",
    "error_type",
    "error_message",
)
"""Columns of ``v_cases`` read from ``cases``."""

_SEAL_COLUMNS: tuple[str, ...] = (
    "name",
    "solver",
    "mesh_engine",
    "mesh_hash",
    "solution_key",
    "request_id",
    "hydromodpy_version",
    "label",
    "label_date",
    "rule_version",
    "nse",
    "score_station",
    "score_variable",
    "score_window_start",
    "score_window_end",
    "n_samples",
    "metric_rule_version",
    "calibrated_by_metric",
    "calibrated_by_cost",
    "calibrated_by_window_start",
    "calibrated_by_window_end",
    "budget_pct",
    "converged",
    "calibrated_by_session_id",
    "duration_s",
)
"""Columns of ``v_cases`` read from ``v_simulation_summary``."""

V_CASES_FIXED_COLUMNS: tuple[str, ...] = _CASE_COLUMNS + _SEAL_COLUMNS
"""The columns ``v_cases`` always carries; the parameter columns come after them."""


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def global_parameter_columns(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Return the global parameter names the index can pivot into ``v_cases``."""
    rows = conn.execute(
        "SELECT DISTINCT param_name FROM parameters WHERE zone_id = ? ORDER BY param_name",
        [CATCHMENT],
    ).fetchall()
    taken = {name.lower() for name in V_CASES_FIXED_COLUMNS}
    return [
        str(row[0])
        for row in rows
        if _IDENTIFIER_RE.match(str(row[0])) and str(row[0]).lower() not in taken
    ]


def _v_cases_ddl(parameter_names: list[str]) -> str:
    select = [f"    c.{name}" for name in _CASE_COLUMNS]
    select.extend(f"    v.{name}" for name in _SEAL_COLUMNS)
    select.extend(f"    p.{_quoted(name)}" for name in parameter_names)
    joins = ["LEFT JOIN v_simulation_summary v ON v.rel_dir = c.rel_dir"]
    if parameter_names:
        pivot = ",\n".join(
            f"        MAX(CASE WHEN param_name = '{name}' THEN value END) AS {_quoted(name)}"
            for name in parameter_names
        )
        joins.append(
            "LEFT JOIN (\n"
            "    SELECT\n"
            "        sim_id,\n"
            f"{pivot}\n"
            f"    FROM parameters WHERE zone_id = '{CATCHMENT}' GROUP BY sim_id\n"
            ") p ON p.sim_id = v.sim_id"
        )
    return (
        "CREATE OR REPLACE VIEW v_cases AS\nSELECT\n"
        + ",\n".join(select)
        + "\nFROM cases c\n"
        + "\n".join(joins)
    )


_V_BEST_PER_PROJECT_DDL = """
CREATE OR REPLACE VIEW v_best_per_project AS
SELECT
    project, sim_id, nse,
    score_station, score_variable, score_window_start, score_window_end, metric_rule_version,
    label, status, created_at
FROM (
    SELECT
        project, sim_id, nse,
        score_station, score_variable, score_window_start, score_window_end, metric_rule_version,
        label, status, created_at,
        ROW_NUMBER() OVER (
            PARTITION BY
                project, score_station, score_variable,
                score_window_start, score_window_end, metric_rule_version
            ORDER BY nse DESC
        ) AS rnk
    FROM v_simulation_summary
    WHERE status = 'completed' AND nse IS NOT NULL
) t
WHERE rnk = 1
"""

_V_METRICS_WIDE_DDL = f"""
CREATE OR REPLACE VIEW v_metrics_wide AS
SELECT
    sim_id,
    station_id,
    variable,
{_wide_metric_columns()}
FROM metrics
WHERE window_name = '{HEADLINE_WINDOW}'
GROUP BY sim_id, station_id, variable
"""

_V_PARAMS_LONG_DDL = f"""
CREATE OR REPLACE VIEW v_params_long AS
SELECT
    sim_id,
    param_name,
    zone_id,
    CASE
        WHEN zone_id = '{CATCHMENT}' THEN param_name
        ELSE param_name || '::' || zone_id
    END AS param_key,
    value,
    unit,
    parameterization,
    origin,
    calibrated
FROM parameters
"""

_V_PARAMS_KEYED_DDL = """
CREATE OR REPLACE VIEW v_params_keyed AS
SELECT sim_id, param_key, value
FROM v_params_long
"""


VIEW_NAMES: tuple[str, ...] = (
    "v_simulation_summary",
    "v_cases",
    "v_best_per_project",
    "v_metrics_wide",
    "v_params_long",
    "v_params_keyed",
)

_FIXED_VIEW_DDL: tuple[str, ...] = (
    _V_SIMULATION_SUMMARY_DDL,
    _V_BEST_PER_PROJECT_DDL,
    _V_METRICS_WIDE_DDL,
    _V_PARAMS_LONG_DDL,
    _V_PARAMS_KEYED_DDL,
)


def ensure_views(conn: duckdb.DuckDBPyConnection) -> None:
    """Create or replace the summary views on an index being written.

    ``v_cases`` is written last, with one column per global parameter the
    ``parameters`` table holds at that moment.
    """
    for ddl in _FIXED_VIEW_DDL:
        conn.execute(ddl)
    conn.execute(_v_cases_ddl(global_parameter_columns(conn)))


__all__ = [
    "VIEW_NAMES",
    "V_CASES_FIXED_COLUMNS",
    "ensure_views",
    "global_parameter_columns",
]
