"""DuckDB schema for the HydroModPy simulation catalog.

Schema v0.6: per-simulation ``timeseries``, ``budgets`` and ``mass_balance``
now live as Parquet files under ``simulations/<uuid>.parquet/`` and are
exposed in DuckDB as views with the original table names. Every other
per-sim table (``parameters``, ``metrics``, ``observation_points``,
``provenance``, ``geographic_features``, ``geographic_metadata``,
``runs_environment``, ``tags``, ``tracked_files``) and the workspace-level
tables (``simulations``, ``stations``, ``observations``,
``calibration_sessions``, ``calibration_iterations``) stay in DuckDB.

This module defines only DDL and helpers; it does not track historical schema
versions. Each major release starts from a fresh schema. Migration principles
for post-P13 evolutions are documented in
``docs/developers/schema_evolution.md``. The Parquet layout and rationale
are described in ``docs/developers/parquet_lakehouse_architecture.md``.

Note on referential integrity: per-sim DuckDB tables carry ``sim_id UUID
NOT NULL`` columns but **no** ``FOREIGN KEY`` clause. DuckDB's foreign-key
engine does not implement ``ON DELETE CASCADE`` and refuses ``UPDATE`` on
a parent row when child rows with composite primary keys still reference
it (issue #duckdb/duckdb#11132 family). The catalog's
:py:meth:`SimulationCatalog.delete` method removes per-sim rows explicitly,
which gives equivalent semantics without the engine bug.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

GLOBAL_ZONE = "__global__"
OUTLET_STATION = "__outlet__"

SOLVER_CATEGORIES: dict[str, str] = {
    "modflownwt": "distributed",
    "modflow6": "distributed",
    "boussinesq": "integrated",
}

# ---------------------------------------------------------------------------
#  Simulations root table
# ---------------------------------------------------------------------------

_SIMULATIONS_DDL = """
CREATE TABLE IF NOT EXISTS simulations (
    sim_id                  UUID PRIMARY KEY,
    name                    VARCHAR,
    project                 VARCHAR NOT NULL,
    solver                  VARCHAR NOT NULL,
    solver_category         VARCHAR,
    flow_regime             VARCHAR
        CHECK (flow_regime IS NULL OR
               flow_regime IN ('steady', 'transient', 'steady_then_transient')),
    status                  VARCHAR NOT NULL DEFAULT 'running'
        CHECK (status IN ('pending', 'running', 'completed',
                          'failed', 'aborted')),
    mesh_topology           VARCHAR
        CHECK (mesh_topology IS NULL OR
               mesh_topology IN ('dis', 'disv', 'disu')),
    mesh_hash               VARCHAR,
    n_cells                 INTEGER,
    n_layers                INTEGER,
    n_timesteps             INTEGER,
    crs_wkt                 VARCHAR,
    crs_epsg                INTEGER,
    bbox_xmin               DOUBLE,
    bbox_ymin               DOUBLE,
    bbox_xmax               DOUBLE,
    bbox_ymax               DOUBLE,
    period_start            TIMESTAMPTZ,
    period_end              TIMESTAMPTZ,
    time_unit               VARCHAR DEFAULT 'day',
    config_toml             JSON,
    config_snapshot         JSON,
    config_hash             VARCHAR,
    config_source           VARCHAR,
    parent_sim_id           UUID,
    lineage_kind            VARCHAR,
    zarr_path               VARCHAR,
    zarr_packed             BOOLEAN NOT NULL DEFAULT FALSE,
    storage_basename        VARCHAR,
    geographic_fingerprint  VARCHAR,
    duration_s              DOUBLE,
    started_at              TIMESTAMPTZ,
    ended_at                TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    tags                    VARCHAR[],
    notes                   VARCHAR,
    CHECK (period_end IS NULL OR period_start IS NULL OR
           period_end >= period_start),
    CHECK (bbox_xmin IS NULL OR bbox_xmax IS NULL OR bbox_xmax >= bbox_xmin),
    CHECK (bbox_ymin IS NULL OR bbox_ymax IS NULL OR bbox_ymax >= bbox_ymin)
);
CREATE INDEX IF NOT EXISTS ix_sim_project ON simulations(project);
CREATE INDEX IF NOT EXISTS ix_sim_solver ON simulations(solver);
CREATE INDEX IF NOT EXISTS ix_sim_status ON simulations(status);
CREATE INDEX IF NOT EXISTS ix_sim_created_at ON simulations(created_at);
CREATE INDEX IF NOT EXISTS ix_sim_config_hash ON simulations(config_hash);
CREATE INDEX IF NOT EXISTS ix_sim_config_source ON simulations(config_source);
CREATE INDEX IF NOT EXISTS ix_sim_mesh_hash ON simulations(mesh_hash);
CREATE INDEX IF NOT EXISTS ix_sim_geo_fp ON simulations(geographic_fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sim_project_name
    ON simulations(project, name);
"""

# ---------------------------------------------------------------------------
#  Parameters, metrics, timeseries, budgets, mass_balance
# ---------------------------------------------------------------------------

_PARAMETERS_DDL = """
CREATE TABLE IF NOT EXISTS parameters (
    sim_id           UUID NOT NULL,
    param_name       VARCHAR NOT NULL,
    zone_id          VARCHAR NOT NULL DEFAULT '__global__',
    value            DOUBLE,
    unit             VARCHAR,
    parameterization VARCHAR DEFAULT 'uniform',
    PRIMARY KEY (sim_id, param_name, zone_id)
);
CREATE INDEX IF NOT EXISTS ix_param_name ON parameters(param_name);
"""

_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS metrics (
    sim_id       UUID NOT NULL,
    station_id   VARCHAR NOT NULL DEFAULT '__outlet__',
    variable     VARCHAR NOT NULL DEFAULT 'head',
    metric_name  VARCHAR NOT NULL,
    value        DOUBLE,
    n_samples    INTEGER,
    period_start TIMESTAMPTZ,
    period_end   TIMESTAMPTZ,
    PRIMARY KEY (sim_id, station_id, variable, metric_name)
);
CREATE INDEX IF NOT EXISTS ix_metrics_metric ON metrics(metric_name);
"""

# ---------------------------------------------------------------------------
#  Observation points and provenance
# ---------------------------------------------------------------------------

_OBSERVATION_POINTS_DDL = """
CREATE TABLE IF NOT EXISTS observation_points (
    sim_id     UUID NOT NULL,
    station_id VARCHAR NOT NULL,
    x          DOUBLE NOT NULL,
    y          DOUBLE NOT NULL,
    cell_id    INTEGER NOT NULL,
    layer      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sim_id, station_id)
);
CREATE INDEX IF NOT EXISTS ix_obs_cell
    ON observation_points(sim_id, cell_id);
"""

_PROVENANCE_DDL = """
CREATE TABLE IF NOT EXISTS provenance (
    sim_id         UUID NOT NULL,
    variable       VARCHAR NOT NULL,
    source_type    VARCHAR NOT NULL
        CHECK (source_type IN ('http_api', 'custom_file',
                               'derived', 'cache')),
    source_ref     VARCHAR NOT NULL,
    source_sha256  VARCHAR,
    payload_sha256 VARCHAR,
    loader_name    VARCHAR,
    loader_version VARCHAR,
    fetched_at     TIMESTAMPTZ,
    period_start   TIMESTAMPTZ,
    period_end     TIMESTAMPTZ,
    n_records      BIGINT,
    stats          JSON,
    PRIMARY KEY (sim_id, variable, source_ref)
);
CREATE INDEX IF NOT EXISTS ix_prov_sha256 ON provenance(source_sha256);
"""

# ---------------------------------------------------------------------------
#  Calibration sessions / iterations
# ---------------------------------------------------------------------------

_CALIBRATION_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS calibration_sessions (
    session_id     UUID PRIMARY KEY,
    project        VARCHAR,
    method         VARCHAR,
    objective_name VARCHAR,
    n_iterations   INTEGER,
    best_sim_id    UUID,
    best_objective DOUBLE,
    config         JSON,
    started_at     TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    duration_s     DOUBLE,
    status         VARCHAR DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed',
                          'failed', 'aborted')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS ix_cal_project ON calibration_sessions(project);
"""

_CALIBRATION_ITERATIONS_DDL = """
CREATE TABLE IF NOT EXISTS calibration_iterations (
    session_id      UUID NOT NULL,
    iteration       INTEGER NOT NULL,
    sim_id          UUID,
    params_hash     VARCHAR,
    parameters      JSON NOT NULL,
    objective_value DOUBLE,
    metrics         JSON,
    status          VARCHAR DEFAULT 'completed'
        CHECK (status IN ('completed', 'diverged', 'timeout',
                          'crashed', 'cached')),
    from_cache      BOOLEAN DEFAULT FALSE,
    duration_s      DOUBLE,
    PRIMARY KEY (session_id, iteration)
);
CREATE INDEX IF NOT EXISTS ix_cal_iter_sim
    ON calibration_iterations(sim_id);
CREATE INDEX IF NOT EXISTS ix_cal_iter_hash
    ON calibration_iterations(params_hash);
"""

# ---------------------------------------------------------------------------
#  Runtime environment provenance
# ---------------------------------------------------------------------------

_RUNS_ENVIRONMENT_DDL = """
CREATE TABLE IF NOT EXISTS runs_environment (
    sim_id              UUID NOT NULL,
    python_version      VARCHAR,
    hydromodpy_version  VARCHAR,
    platform            VARCHAR,
    hostname            VARCHAR,
    user_name           VARCHAR,
    cpu_info            JSON,
    memory_gb           DOUBLE,
    git_commit          VARCHAR,
    env_packages        JSON,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (sim_id)
);
"""

_TAGS_DDL = """
CREATE TABLE IF NOT EXISTS tags (
    sim_id   UUID NOT NULL,
    tag      VARCHAR NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    added_by VARCHAR,
    PRIMARY KEY (sim_id, tag)
);
CREATE INDEX IF NOT EXISTS ix_tags_tag ON tags(tag);
"""

_STATIONS_DDL = """
CREATE TABLE IF NOT EXISTS stations (
    station_id    VARCHAR NOT NULL,
    name          VARCHAR,
    latitude      DOUBLE,
    longitude     DOUBLE,
    elevation     DOUBLE,
    variable_type VARCHAR NOT NULL,
    source        VARCHAR,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    first_valid   DATE,
    last_valid    DATE,
    metadata      JSON,
    PRIMARY KEY (station_id, variable_type)
);
CREATE INDEX IF NOT EXISTS ix_stations_variable ON stations(variable_type);
CREATE INDEX IF NOT EXISTS ix_stations_active ON stations(active);
"""

_OBSERVATIONS_DDL = """
CREATE TABLE IF NOT EXISTS observations (
    station_id    VARCHAR NOT NULL,
    variable_type VARCHAR NOT NULL,
    datetime      TIMESTAMPTZ NOT NULL,
    value         DOUBLE,
    unit          VARCHAR,
    quality       VARCHAR,
    PRIMARY KEY (station_id, variable_type, datetime)
);
CREATE INDEX IF NOT EXISTS ix_observations_station
    ON observations(station_id, variable_type, datetime);
CREATE INDEX IF NOT EXISTS ix_observations_datetime
    ON observations(datetime);
"""

# ---------------------------------------------------------------------------
#  Geographic tables
# ---------------------------------------------------------------------------

_GEOGRAPHIC_FEATURES_DDL = """
CREATE TABLE IF NOT EXISTS geographic_features (
    sim_id          UUID NOT NULL,
    feature_name    VARCHAR NOT NULL,
    geometry_kind   VARCHAR
        CHECK (geometry_kind IS NULL OR
               geometry_kind IN ('point', 'linestring',
                                 'polygon', 'multipolygon')),
    crs_wkt         VARCHAR,
    geoparquet_path VARCHAR,
    properties      JSON,
    PRIMARY KEY (sim_id, feature_name)
);
"""

_GEOGRAPHIC_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS geographic_metadata (
    sim_id     UUID NOT NULL,
    key        VARCHAR NOT NULL,
    value      VARCHAR,
    value_type VARCHAR NOT NULL DEFAULT 'string'
        CHECK (value_type IN ('double', 'int', 'string', 'bool')),
    unit       VARCHAR,
    PRIMARY KEY (sim_id, key)
);
"""

_TRACKED_FILES_DDL = """
CREATE TABLE IF NOT EXISTS tracked_files (
    sim_id         UUID NOT NULL,
    role           VARCHAR NOT NULL,
    category       VARCHAR NOT NULL,
    original_path  VARCHAR NOT NULL,
    canonical_path VARCHAR NOT NULL,
    sha256         VARCHAR NOT NULL,
    size_bytes     BIGINT NOT NULL,
    portable       BOOLEAN NOT NULL DEFAULT TRUE,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (sim_id, role, canonical_path)
);
CREATE INDEX IF NOT EXISTS ix_tracked_files_sha ON tracked_files(sha256);
"""

# ---------------------------------------------------------------------------
#  Denormalized views (G05)
# ---------------------------------------------------------------------------

_V_SIMULATION_SUMMARY_DDL = """
CREATE OR REPLACE VIEW v_simulation_summary AS
SELECT
    s.sim_id,
    s.project,
    s.status,
    s.solver,
    s.flow_regime,
    s.created_at,
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
LEFT JOIN metrics m ON s.sim_id = m.sim_id
GROUP BY s.sim_id, s.project, s.status, s.solver, s.flow_regime,
         s.created_at, s.duration_s
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

# Known metric names (keep in sync with write paths). PIVOT in a view
# requires a fixed IN-list, so metric names outside this list will not show up
# in ``v_metrics_wide`` — they remain queryable via the ``metrics`` table.
_KNOWN_METRIC_NAMES = (
    "nse",
    "kge",
    "rmse",
    "r2",
    "bias",
    "pbias",
    "mae",
    "mse",
)

_V_METRICS_WIDE_DDL = f"""
CREATE OR REPLACE VIEW v_metrics_wide AS
PIVOT metrics
ON metric_name IN ({", ".join(f"'{n}'" for n in _KNOWN_METRIC_NAMES)})
USING FIRST(value)
"""

# Parameter names vary by simulation, so PIVOT cannot be used in a view.
# Instead we aggregate into a MAP keyed by ``param_name`` (or
# ``param_name::zone_id`` when the parameter is zonal) so callers can index
# the map directly or unnest as needed.
_V_PARAMS_WIDE_DDL = """
CREATE OR REPLACE VIEW v_params_wide AS
SELECT
    sim_id,
    MAP(
        LIST(
            CASE
                WHEN zone_id = '__global__' THEN param_name
                ELSE param_name || '::' || zone_id
            END
        ),
        LIST(value)
    ) AS params
FROM parameters
GROUP BY sim_id
"""

VIEW_NAMES: tuple[str, ...] = (
    "v_simulation_summary",
    "v_best_per_project",
    "v_metrics_wide",
    "v_params_wide",
)

_ALL_VIEW_DDL: tuple[str, ...] = (
    _V_SIMULATION_SUMMARY_DDL,
    _V_BEST_PER_PROJECT_DDL,
    _V_METRICS_WIDE_DDL,
    _V_PARAMS_WIDE_DDL,
)

# ---------------------------------------------------------------------------
#  Public constants and entry points
# ---------------------------------------------------------------------------

TABLE_NAMES: tuple[str, ...] = (
    "simulations",
    "parameters",
    "metrics",
    "observation_points",
    "provenance",
    "calibration_sessions",
    "calibration_iterations",
    "geographic_features",
    "geographic_metadata",
    "runs_environment",
    "tags",
    "stations",
    "observations",
    "tracked_files",
)

# DuckDB-resident per-simulation tables. The Parquet-backed per-simulation
# views (``timeseries``, ``budgets``, ``mass_balance``) are listed separately
# in :data:`PARQUET_VIEW_NAMES` — they are never touched by SQL DELETE
# statements because they are not tables.
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
)

# Per-simulation Parquet files, named by their view alias. Each file lives
# at ``simulations/<uuid>.parquet/<name>.parquet`` in the workspace.
PARQUET_VIEW_NAMES: tuple[str, ...] = (
    "timeseries",
    "budgets",
    "mass_balance",
)

_ALL_DDL: tuple[str, ...] = (
    _SIMULATIONS_DDL,
    _PARAMETERS_DDL,
    _METRICS_DDL,
    _OBSERVATION_POINTS_DDL,
    _PROVENANCE_DDL,
    _CALIBRATION_SESSIONS_DDL,
    _CALIBRATION_ITERATIONS_DDL,
    _GEOGRAPHIC_FEATURES_DDL,
    _GEOGRAPHIC_METADATA_DDL,
    _RUNS_ENVIRONMENT_DDL,
    _TAGS_DDL,
    _STATIONS_DDL,
    _OBSERVATIONS_DDL,
    _TRACKED_FILES_DDL,
)

# ---------------------------------------------------------------------------
#  Parquet-backed views (timeseries / budgets / mass_balance)
# ---------------------------------------------------------------------------

_PARQUET_VIEW_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "timeseries": (
        ("sim_id", "UUID"),
        ("station_id", "VARCHAR"),
        ("variable", "VARCHAR"),
        ("datetime", "TIMESTAMPTZ"),
        ("value", "DOUBLE"),
        ("unit", "VARCHAR"),
        ("qflag", "VARCHAR"),
    ),
    "budgets": (
        ("sim_id", "UUID"),
        ("timestep", "INTEGER"),
        ("zone_id", "VARCHAR"),
        ("component", "VARCHAR"),
        ("flux_in", "DOUBLE"),
        ("flux_out", "DOUBLE"),
        ("unit", "VARCHAR"),
    ),
    "mass_balance": (
        ("sim_id", "UUID"),
        ("timestep", "INTEGER"),
        ("total_in", "DOUBLE"),
        ("total_out", "DOUBLE"),
        ("storage_in", "DOUBLE"),
        ("storage_out", "DOUBLE"),
        ("percent_error", "DOUBLE"),
        ("unit", "VARCHAR"),
    ),
}


def parquet_view_columns(view_name: str) -> tuple[tuple[str, str], ...]:
    """Return ``((col, type), ...)`` for one of the three Parquet views."""
    try:
        return _PARQUET_VIEW_COLUMNS[view_name]
    except KeyError as exc:
        raise KeyError(f"Unknown Parquet view: {view_name!r}") from exc


def _empty_view_ddl(view_name: str) -> str:
    cols = _PARQUET_VIEW_COLUMNS[view_name]
    casts = ",\n    ".join(f"CAST(NULL AS {t}) AS {c}" for c, t in cols)
    return f"CREATE OR REPLACE VIEW {view_name} AS SELECT\n    {casts}\nWHERE 1=0"


def _read_parquet_view_ddl(view_name: str, glob_path: str) -> str:
    # read_parquet preserves UUID and TIMESTAMPTZ as DuckDB native types, so
    # an explicit cast on read is not required — see the unit test in
    # ``tests/unit/results/test_parquet_view_types.py``.
    escaped = glob_path.replace("'", "''")
    return (
        f"CREATE OR REPLACE VIEW {view_name} AS "
        f"SELECT * FROM read_parquet('{escaped}', union_by_name=true)"
    )


def _glob_for_view(workspace_path: Path, view_name: str) -> str:
    return str(workspace_path / "simulations" / "*.parquet" / f"{view_name}.parquet")


def _parquet_files_exist(workspace_path: Path, view_name: str) -> bool:
    sim_root = workspace_path / "simulations"
    if not sim_root.is_dir():
        return False
    return any(sim_root.glob(f"*.parquet/{view_name}.parquet"))


def ensure_parquet_views(conn: duckdb.DuckDBPyConnection, workspace_path: Path) -> None:
    """Create or refresh the three Parquet-backed views on ``conn``.

    If no matching Parquet file exists for a given view, an empty typed
    view is installed so that ``SELECT * FROM <view>`` still succeeds with
    the right columns on a fresh workspace. On the next write that creates
    the first file, the catalog calls this function again to swap the view
    over to ``read_parquet``. If a legacy DuckDB table with the same name as
    a target view still exists, view creation is skipped so the caller can
    still query its rows; legacy workspaces should be regenerated.
    """
    legacy_tables = {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_type='BASE TABLE'"
        ).fetchall()
    }
    for view in PARQUET_VIEW_NAMES:
        if view in legacy_tables:
            logger.warning(
                "Skipping view %r: a legacy DuckDB table with that name still "
                "exists. Regenerate the workspace to use the Parquet layout.",
                view,
            )
            continue
        if _parquet_files_exist(workspace_path, view):
            ddl = _read_parquet_view_ddl(view, _glob_for_view(workspace_path, view))
        else:
            ddl = _empty_view_ddl(view)
        conn.execute(ddl)


# Forward-only column additions applied to the ``simulations`` table on every
# ``ensure_schema`` call. ``CREATE TABLE IF NOT EXISTS`` is a no-op when the
# table already exists, so a new column added to the DDL never reaches a
# pre-existing catalog. This lightweight list keeps dev-branch upgrades
# painless without introducing a full versioned migration system.
_SIMULATIONS_ADDITIVE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("config_source", "VARCHAR"),
    ("storage_basename", "VARCHAR"),
)


def _apply_simulations_additive_columns(conn: duckdb.DuckDBPyConnection) -> None:
    """Add missing columns to ``simulations`` without touching existing rows."""
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'simulations'"
        ).fetchall()
    }
    for name, sql_type in _SIMULATIONS_ADDITIVE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE simulations ADD COLUMN {name} {sql_type}")
            logger.info("DuckDB schema upgrade: added simulations.%s", name)


def ensure_schema(
    conn: duckdb.DuckDBPyConnection,
    workspace_path: Path | None = None,
) -> None:
    """Create the catalog tables and views if they do not already exist.

    Idempotent: repeated calls on the same connection are safe. Additive
    column evolutions declared in ``_SIMULATIONS_ADDITIVE_COLUMNS`` are
    back-filled into pre-existing catalogs via ``ALTER TABLE`` so that
    upgrades don't require wiping ``hydromodpy.duckdb``. See
    ``docs/developers/schema_evolution.md`` for broader evolution rules.

    Ordering matters: ``CREATE TABLE IF NOT EXISTS`` for an already-existing
    table is a no-op, so additive columns must be applied *before* any
    ``CREATE INDEX`` statement that targets them — otherwise DuckDB refuses
    the index with ``Binder Error: Table X does not have a column named Y``.

    When ``workspace_path`` is given, the three Parquet-backed views are
    installed too (empty-typed until the first file lands).
    """
    # Phase 1: create tables only (no indexes that could reference new cols).
    for ddl in _ALL_DDL:
        for stmt in _iter_statements_without_index(ddl):
            conn.execute(stmt)

    # Phase 2: migrate pre-existing tables to the current column set.
    _apply_simulations_additive_columns(conn)
    _drop_legacy_parquet_tables(conn)

    # Phase 3: (re-)create indexes now that every referenced column exists.
    for ddl in _ALL_DDL:
        for stmt in _iter_index_statements(ddl):
            conn.execute(stmt)

    for ddl in _ALL_VIEW_DDL:
        conn.execute(ddl)

    if workspace_path is not None:
        ensure_parquet_views(conn, Path(workspace_path))

    logger.debug(
        "DuckDB catalog schema ensured (%d tables, %d views, %d parquet views)",
        len(TABLE_NAMES),
        len(VIEW_NAMES),
        len(PARQUET_VIEW_NAMES),
    )


def _drop_legacy_parquet_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Drop pre-refactor ``timeseries`` / ``budgets`` / ``mass_balance``
    tables if they still exist in the DuckDB file.

    A table and a view cannot share a name. When opening a pre-refactor
    catalog, the old tables must be dropped before the Parquet views can
    be created. This function is a no-op when the names are already bound
    to views or are absent. Non-empty legacy tables are left in place and
    log a warning; the workspace must be regenerated.
    """
    rows = conn.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name IN ('timeseries', 'budgets', 'mass_balance')"
    ).fetchall()
    for name, kind in rows:
        if kind == "BASE TABLE":
            count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            if count:
                logger.warning(
                    "Catalog still has %d rows in legacy table %r — "
                    "regenerate the workspace to migrate to the Parquet layout.",
                    count,
                    name,
                )
                continue
            conn.execute(f'DROP TABLE "{name}"')


def _iter_statements_without_index(ddl: str):
    """Yield every statement in ``ddl`` that is NOT a CREATE INDEX."""
    for stmt in _split_ddl_statements(ddl):
        if not stmt.upper().startswith("CREATE") or "INDEX" not in stmt.upper().split("\n", 1)[0]:
            yield stmt


def _iter_index_statements(ddl: str):
    """Yield every CREATE INDEX statement in ``ddl``."""
    for stmt in _split_ddl_statements(ddl):
        head = stmt.upper().split("\n", 1)[0]
        if head.startswith("CREATE") and "INDEX" in head:
            yield stmt


def _split_ddl_statements(ddl: str) -> list[str]:
    """Split a multi-statement DDL string on top-level semicolons.

    Naive but sufficient — our DDL strings contain no string literals that
    embed a semicolon.
    """
    parts = [s.strip() for s in ddl.split(";")]
    return [f"{s};" for s in parts if s]
