"""DuckDB schema for project results and workspace simulation registry."""

from __future__ import annotations

import duckdb

_PROJECT_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS simulations (
    sim_id        UUID PRIMARY KEY,
    name          VARCHAR,
    created_at    TIMESTAMP DEFAULT now(),
    config_toml   JSON,
    solver        VARCHAR,
    n_cells       INTEGER,
    n_layers      INTEGER,
    n_timesteps   INTEGER,
    cell_types    VARCHAR[],
    bbox          DOUBLE[4],
    zarr_group    VARCHAR,
    status        VARCHAR,
    duration_s    DOUBLE,
    tags          VARCHAR[],
    calibration_params JSON
);

CREATE TABLE IF NOT EXISTS timeseries (
    sim_id        UUID REFERENCES simulations(sim_id),
    station_id    VARCHAR,
    variable      VARCHAR,
    timestamps    TIMESTAMP[],
    values        DOUBLE[],
    unit          VARCHAR
);

CREATE TABLE IF NOT EXISTS budgets (
    sim_id        UUID REFERENCES simulations(sim_id),
    timestep      INTEGER,
    zone_id       INTEGER,
    component     VARCHAR,
    flux_in       DOUBLE,
    flux_out      DOUBLE,
    unit          VARCHAR
);

CREATE TABLE IF NOT EXISTS metrics (
    sim_id        UUID REFERENCES simulations(sim_id),
    station_id    VARCHAR,
    metric_name   VARCHAR,
    value         DOUBLE
);

CREATE TABLE IF NOT EXISTS observation_points (
    sim_id        UUID REFERENCES simulations(sim_id),
    station_id    VARCHAR,
    x             DOUBLE,
    y             DOUBLE,
    cell_id       INTEGER,
    layer         INTEGER DEFAULT 0,
    variable      VARCHAR
);

CREATE TABLE IF NOT EXISTS mass_balance_summary (
    sim_id         UUID REFERENCES simulations(sim_id),
    timestep       INTEGER,
    total_in       DOUBLE,
    total_out      DOUBLE,
    storage_in     DOUBLE,
    storage_out    DOUBLE,
    percent_error  DOUBLE
);

CREATE TABLE IF NOT EXISTS input_provenance (
    sim_id        UUID REFERENCES simulations(sim_id),
    variable      VARCHAR,
    source_type   VARCHAR,
    source_ref    VARCHAR,
    period_start  DATE,
    period_end    DATE,
    checksum      VARCHAR,
    n_records     INTEGER,
    stats         JSON
);
"""

_REGISTRY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS simulation_registry (
    sim_id         UUID PRIMARY KEY,
    project        VARCHAR NOT NULL,
    project_path   TEXT NOT NULL,
    name           VARCHAR,
    description    VARCHAR,
    tags           VARCHAR[],
    created_at     TIMESTAMP DEFAULT now(),
    solver         VARCHAR NOT NULL,
    process_types  VARCHAR[],
    status         VARCHAR NOT NULL,
    n_cells        INTEGER,
    n_layers       INTEGER,
    cell_types     VARCHAR[],
    bbox           DOUBLE[4],
    crs            VARCHAR,
    n_timesteps    INTEGER,
    period_start   DATE,
    period_end     DATE,
    time_unit      VARCHAR,
    duration_s     DOUBLE,
    best_nse       DOUBLE,
    best_kge       DOUBLE,
    best_rmse      DOUBLE,
    n_observation_points INTEGER,
    forcing_sources VARCHAR[],
    config_hash     VARCHAR
);

CREATE INDEX IF NOT EXISTS ix_registry_project ON simulation_registry(project);
CREATE INDEX IF NOT EXISTS ix_registry_solver ON simulation_registry(solver);
CREATE INDEX IF NOT EXISTS ix_registry_status ON simulation_registry(status);
CREATE INDEX IF NOT EXISTS ix_registry_created ON simulation_registry(created_at);
"""

PROJECT_TABLE_NAMES = (
    "simulations",
    "timeseries",
    "budgets",
    "metrics",
    "observation_points",
    "mass_balance_summary",
    "input_provenance",
)


def create_project_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all result tables in a project database.

    Safe to call multiple times (IF NOT EXISTS).
    """
    conn.execute(_PROJECT_TABLES_SQL)


def create_registry_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the simulation_registry table in the workspace catalog database.

    Safe to call multiple times (IF NOT EXISTS).
    """
    conn.execute(_REGISTRY_TABLE_SQL)
