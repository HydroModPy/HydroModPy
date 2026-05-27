"""Materialised DuckDB views used by the catalog read path.

These views are installed by :class:`SimulationCatalog` after the migration
runner has applied the latest DDL. They expose denormalised projections of
the v2 schema, joining the dimension tables (``solvers``, ``statuses``,
``flow_regimes``, ``mesh_topologies``) so callers can keep using the
familiar ``solver`` / ``status`` text labels without manually JOINing.

The DDL is written in a Postgres-compatible subset: no ``PIVOT``, no
``MAP``, no ``QUALIFY``. Wide metric views are built via ``MAX(CASE
WHEN ...)`` aggregation; wide parameter views are exposed as long-form
``v_params_long`` with a side helper view ``v_params_keyed`` that
materialises the ``param_name`` / ``zone_id`` join key as a single
column (so callers can pivot in pandas without touching SQL).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb


# Known metric names. Wide projections require a fixed IN-list because
# CASE WHEN aggregation needs explicit columns. Metric names outside this
# list will not show up in ``v_metrics_wide``; they remain queryable via
# the ``metrics`` table directly.
_KNOWN_METRIC_NAMES: tuple[str, ...] = (
    "nse",
    "kge",
    "rmse",
    "r2",
    "bias",
    "pbias",
    "mae",
    "mse",
    "closure_n_periods",
    "closure_max_abs_m3_s",
    "closure_mean_abs_m3_s",
    "closure_rmse_m3_s",
    "closure_max_abs_mm_d",
    "closure_relative_error_p95",
    "closure_status_code",
)


def _wide_metric_columns() -> str:
    """Return the ``MAX(CASE WHEN ...)`` projection clauses for metrics."""
    lines = []
    for name in _KNOWN_METRIC_NAMES:
        safe = name.replace("'", "''")
        lines.append(f"    MAX(CASE WHEN metric_name = '{safe}' THEN value END) AS {name}")
    return ",\n".join(lines)


_V_SIMULATION_SUMMARY_DDL = """
CREATE OR REPLACE VIEW v_simulation_summary AS
SELECT
    s.sim_id,
    s.name,
    s.project,
    st.code AS status,
    sv.code AS solver,
    sv.category AS solver_category,
    fr.code AS flow_regime,
    mt.code AS mesh_topology,
    s.study_area_name,
    s.scientific_objective,
    s.description,
    s.contact_email,
    s.principal_id,
    s.bbox_xmin,
    s.bbox_ymin,
    s.bbox_xmax,
    s.bbox_ymax,
    s.period_start,
    s.period_end,
    s.created_at,
    s.updated_at,
    s.duration_s,
    MAX(CASE WHEN m.metric_name = 'nse'
             AND m.station_id = '__outlet__'
             AND m.variable = 'head' THEN m.value END)  AS nse,
    MAX(CASE WHEN m.metric_name = 'kge'
             AND m.station_id = '__outlet__'
             AND m.variable = 'head' THEN m.value END)  AS kge,
    MAX(CASE WHEN m.metric_name = 'rmse'
             AND m.station_id = '__outlet__'
             AND m.variable = 'head' THEN m.value END)  AS rmse,
    MAX(CASE WHEN m.metric_name = 'r2'
             AND m.station_id = '__outlet__'
             AND m.variable = 'head' THEN m.value END)  AS r2
FROM simulations s
JOIN solvers sv ON s.solver_id = sv.id
JOIN statuses st ON s.status_id = st.id
LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id
LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id
LEFT JOIN metrics m ON s.sim_id = m.sim_id
GROUP BY
    s.sim_id,
    s.name,
    s.project,
    st.code,
    sv.code,
    sv.category,
    fr.code,
    mt.code,
    s.study_area_name,
    s.scientific_objective,
    s.description,
    s.contact_email,
    s.principal_id,
    s.bbox_xmin,
    s.bbox_ymin,
    s.bbox_xmax,
    s.bbox_ymax,
    s.period_start,
    s.period_end,
    s.created_at,
    s.updated_at,
    s.duration_s
"""

_V_BEST_PER_PROJECT_DDL = """
CREATE OR REPLACE VIEW v_best_per_project AS
SELECT project, sim_id, nse, kge, rmse, r2, status, created_at
FROM (
    SELECT
        project, sim_id, nse, kge, rmse, r2, status, created_at,
        ROW_NUMBER() OVER (
            PARTITION BY project
            ORDER BY nse DESC NULLS LAST
        ) AS rnk
    FROM v_simulation_summary
    WHERE status = 'completed'
) t
WHERE rnk = 1
"""


_V_METRICS_WIDE_DDL = f"""
CREATE OR REPLACE VIEW v_metrics_wide AS
SELECT
    sim_id,
{_wide_metric_columns()}
FROM metrics
GROUP BY sim_id
"""


# Parameter names vary by simulation and PIVOT/MAP are non-portable.
# Expose a long-form view that callers can pivot in pandas (a single
# ``pivot_table`` call) without touching dialect-specific SQL.
_V_PARAMS_LONG_DDL = """
CREATE OR REPLACE VIEW v_params_long AS
SELECT
    sim_id,
    param_name,
    zone_id,
    CASE
        WHEN zone_id = '__global__' THEN param_name
        ELSE param_name || '::' || zone_id
    END AS param_key,
    value,
    unit,
    parameterization
FROM parameters
"""


# Backwards-compatible alias kept as a SELECT-only projection so callers
# can keep importing ``v_params_wide`` without an SQL error. The aggregated
# wide form is intentionally not materialised at the SQL level; pandas does
# the pivot on the long-form output from ``v_params_long``.
_V_PARAMS_WIDE_DDL = """
CREATE OR REPLACE VIEW v_params_wide AS
SELECT sim_id, param_key, value
FROM v_params_long
"""


VIEW_NAMES: tuple[str, ...] = (
    "v_simulation_summary",
    "v_best_per_project",
    "v_metrics_wide",
    "v_params_long",
    "v_params_wide",
)

_ALL_VIEW_DDL: tuple[str, ...] = (
    _V_SIMULATION_SUMMARY_DDL,
    _V_BEST_PER_PROJECT_DDL,
    _V_METRICS_WIDE_DDL,
    _V_PARAMS_LONG_DDL,
    _V_PARAMS_WIDE_DDL,
)


def ensure_views(conn: duckdb.DuckDBPyConnection) -> None:
    """Create or replace the catalog summary views.

    Safe to call repeatedly. Depends on the v2 schema being present (the
    migration runner must have applied the initial DDL first).
    """
    for ddl in _ALL_VIEW_DDL:
        conn.execute(ddl)


__all__ = [
    "VIEW_NAMES",
    "ensure_views",
]
