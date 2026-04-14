from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)

LATEST_VERSION = 1

HOMOGENEOUS_ZONE = "_homogeneous"

SOLVER_CATEGORIES: dict[str, str] = {
    "modflownwt": "distributed",
    "modflow6": "distributed",
    "boussinesq": "integrated",
}

# -- DDL ---------------------------------------------------------------------

_SCHEMA_VERSION_DDL = """\
CREATE TABLE IF NOT EXISTS _schema_version (
    version    INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT now()
);
"""

_SIMULATIONS_DDL = """\
CREATE TABLE IF NOT EXISTS simulations (
    sim_id          UUID PRIMARY KEY,
    name            VARCHAR,
    project         VARCHAR NOT NULL,
    solver          VARCHAR,
    solver_category VARCHAR,
    flow_regime     VARCHAR,
    n_cells         INTEGER,
    n_layers        INTEGER,
    n_timesteps     INTEGER,
    cell_types      VARCHAR[],
    bbox            DOUBLE[4],
    crs             VARCHAR,
    period_start    VARCHAR,
    period_end      VARCHAR,
    time_unit       VARCHAR,
    config_toml     JSON,
    config_hash     VARCHAR,
    zarr_path       VARCHAR,
    parent_sim_id   UUID,
    mesh_hash       VARCHAR,
    mesh_type       VARCHAR,
    status          VARCHAR DEFAULT 'running',
    duration_s      DOUBLE,
    created_at      TIMESTAMP DEFAULT now(),
    tags            VARCHAR[],
    notes           VARCHAR
);
CREATE INDEX IF NOT EXISTS ix_sim_project ON simulations(project);
CREATE INDEX IF NOT EXISTS ix_sim_solver ON simulations(solver);
CREATE INDEX IF NOT EXISTS ix_sim_status ON simulations(status);
CREATE INDEX IF NOT EXISTS ix_sim_created ON simulations(created_at);
"""

_PARAMETERS_DDL = """\
CREATE TABLE IF NOT EXISTS parameters (
    sim_id           UUID NOT NULL,
    param_name       VARCHAR NOT NULL,
    zone_id          VARCHAR NOT NULL DEFAULT '_homogeneous',
    value            DOUBLE,
    unit             VARCHAR,
    parameterization VARCHAR,
    PRIMARY KEY (sim_id, param_name, zone_id)
);
"""

_TIMESERIES_DDL = """\
CREATE TABLE IF NOT EXISTS timeseries (
    sim_id     UUID NOT NULL,
    station_id VARCHAR NOT NULL,
    variable   VARCHAR NOT NULL,
    timestamp  TIMESTAMP NOT NULL,
    value      DOUBLE,
    unit       VARCHAR
);
CREATE INDEX IF NOT EXISTS ix_ts_lookup
    ON timeseries(sim_id, station_id, variable, timestamp);
"""

_BUDGETS_DDL = """\
CREATE TABLE IF NOT EXISTS budgets (
    sim_id    UUID NOT NULL,
    timestep  INTEGER,
    zone_id   VARCHAR,
    component VARCHAR,
    flux_in   DOUBLE,
    flux_out  DOUBLE,
    unit      VARCHAR DEFAULT 'm3/d'
);
"""

_MASS_BALANCE_DDL = """\
CREATE TABLE IF NOT EXISTS mass_balance (
    sim_id        UUID NOT NULL,
    timestep      INTEGER,
    total_in      DOUBLE,
    total_out     DOUBLE,
    storage_in    DOUBLE,
    storage_out   DOUBLE,
    percent_error DOUBLE
);
"""

_METRICS_DDL = """\
CREATE TABLE IF NOT EXISTS metrics (
    sim_id      UUID NOT NULL,
    station_id  VARCHAR NOT NULL,
    metric_name VARCHAR NOT NULL,
    value       DOUBLE,
    PRIMARY KEY (sim_id, station_id, metric_name)
);
"""

_OBSERVATION_POINTS_DDL = """\
CREATE TABLE IF NOT EXISTS observation_points (
    sim_id     UUID NOT NULL,
    station_id VARCHAR,
    x          DOUBLE,
    y          DOUBLE,
    cell_id    INTEGER,
    layer      INTEGER DEFAULT 0,
    variable   VARCHAR
);
"""

_PROVENANCE_DDL = """\
CREATE TABLE IF NOT EXISTS provenance (
    sim_id       UUID NOT NULL,
    variable     VARCHAR,
    source_type  VARCHAR,
    source_ref   VARCHAR,
    checksum     VARCHAR,
    period_start VARCHAR,
    period_end   VARCHAR,
    n_records    INTEGER,
    stats        JSON
);
"""

_CALIBRATION_SESSIONS_DDL = """\
CREATE TABLE IF NOT EXISTS calibration_sessions (
    session_id     UUID PRIMARY KEY,
    best_sim_id    UUID,
    method         VARCHAR,
    n_iterations   INTEGER,
    best_objective DOUBLE,
    duration_s     DOUBLE,
    config         JSON,
    created_at     TIMESTAMP DEFAULT now()
);
"""

_CALIBRATION_ITERATIONS_DDL = """\
CREATE TABLE IF NOT EXISTS calibration_iterations (
    session_id      UUID NOT NULL,
    iteration       INTEGER NOT NULL,
    parameters      JSON,
    objective_value DOUBLE,
    metrics         JSON,
    duration_s      DOUBLE,
    PRIMARY KEY (session_id, iteration)
);
"""

_GEOGRAPHIC_FEATURES_DDL = """\
CREATE TABLE IF NOT EXISTS geographic_features (
    project       VARCHAR NOT NULL,
    feature_name  VARCHAR NOT NULL,
    geojson       TEXT,
    geometry_type VARCHAR,
    crs           VARCHAR,
    properties    JSON,
    PRIMARY KEY (project, feature_name)
);
"""

_GEOGRAPHIC_METADATA_DDL = """\
CREATE TABLE IF NOT EXISTS geographic_metadata (
    project VARCHAR NOT NULL,
    key     VARCHAR NOT NULL,
    value   VARCHAR,
    PRIMARY KEY (project, key)
);
"""

_ALL_DDL = [
    _SIMULATIONS_DDL,
    _PARAMETERS_DDL,
    _TIMESERIES_DDL,
    _BUDGETS_DDL,
    _MASS_BALANCE_DDL,
    _METRICS_DDL,
    _OBSERVATION_POINTS_DDL,
    _PROVENANCE_DDL,
    _CALIBRATION_SESSIONS_DDL,
    _CALIBRATION_ITERATIONS_DDL,
    _GEOGRAPHIC_FEATURES_DDL,
    _GEOGRAPHIC_METADATA_DDL,
]

# -- Public constants --------------------------------------------------------

TABLE_NAMES: tuple[str, ...] = (
    "simulations",
    "parameters",
    "timeseries",
    "budgets",
    "mass_balance",
    "metrics",
    "observation_points",
    "provenance",
    "calibration_sessions",
    "calibration_iterations",
    "geographic_features",
    "geographic_metadata",
)

PER_SIM_TABLE_NAMES: tuple[str, ...] = (
    "parameters",
    "timeseries",
    "budgets",
    "mass_balance",
    "metrics",
    "observation_points",
    "provenance",
)

MIGRATIONS: dict[int, list[str]] = {
    # 1: [],  # initial schema, no migration needed
}

# -- Schema versioning -------------------------------------------------------


def _get_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        if "_schema_version" not in tables:
            return 0
        row = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()
        return row[0] if row and row[0] is not None else 0
    except Exception:
        return 0


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_SCHEMA_VERSION_DDL)
    current = _get_schema_version(conn)

    if current >= LATEST_VERSION:
        for ddl in _ALL_DDL:
            conn.execute(ddl)
        return

    for ddl in _ALL_DDL:
        conn.execute(ddl)

    for v in range(current + 1, LATEST_VERSION + 1):
        for stmt in MIGRATIONS.get(v, []):
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO _schema_version (version) VALUES (?)", [v]
        )
        logger.debug("Schema stamped at version %d", v)
