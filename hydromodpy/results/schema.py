"""DuckDB schema for project results and workspace simulation registry.

Includes schema versioning with automatic migrations so that existing
``project.duckdb`` files are upgraded transparently.
"""

from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)

# -- Schema version ----------------------------------------------------------

_CURRENT_SCHEMA_VERSION = 3

_SCHEMA_VERSION_DDL = """\
CREATE TABLE IF NOT EXISTS _schema_version (
    version    INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT now()
);
"""

# -- Project tables (version 1) ---------------------------------------------

_PROJECT_TABLES_SQL = """\
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
    station_id    VARCHAR NOT NULL,
    variable      VARCHAR NOT NULL,
    timestamp     TIMESTAMP NOT NULL,
    value         DOUBLE,
    unit          VARCHAR
);

CREATE INDEX IF NOT EXISTS ix_ts_lookup
    ON timeseries(sim_id, station_id, variable, timestamp);

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

# -- Geographic tables (version 2) ------------------------------------------

_GEOGRAPHIC_TABLES_SQL = """\
CREATE TABLE IF NOT EXISTS geographic_metadata (
    key    VARCHAR PRIMARY KEY,
    value  VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS geographic_features (
    feature_name   VARCHAR PRIMARY KEY,
    geometry_wkb   BLOB NOT NULL,
    geometry_type  VARCHAR,
    crs            VARCHAR,
    properties     JSON,
    geojson        TEXT
);
"""

# -- Public constants --------------------------------------------------------

PROJECT_TABLE_NAMES = (
    "timeseries",
    "budgets",
    "metrics",
    "observation_points",
    "mass_balance_summary",
    "input_provenance",
    "simulations",
)

# Tables without sim_id (project-level, not per-simulation).
# Not included in PROJECT_TABLE_NAMES because delete_simulation
# iterates over that tuple to cascade deletions by sim_id.
PROJECT_GEOGRAPHIC_TABLE_NAMES = (
    "geographic_metadata",
    "geographic_features",
)

SIMULATIONS_COLUMNS = frozenset({
    "sim_id", "name", "created_at", "solver",
    "n_cells", "n_layers", "n_timesteps",
    "status", "duration_s",
})
"""Column names accepted by :meth:`ResultStore.list_simulations` filters."""


# -- Schema versioning helpers -----------------------------------------------

def _get_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    """Return the current schema version, ``0`` if unversioned."""
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
        return row[0] if row[0] is not None else 0
    except Exception:
        return 0


def _ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Stamp the schema version if not already set, apply migrations."""
    conn.execute(_SCHEMA_VERSION_DDL)
    current = _get_schema_version(conn)

    if current >= _CURRENT_SCHEMA_VERSION:
        return

    # Migration: v1 → v2 (geographic tables)
    if current < 2:
        conn.execute(_GEOGRAPHIC_TABLES_SQL)
        logger.debug("Applied migration v1 → v2: geographic tables")

    # Migration: v2 → v3 (geojson column for multi-feature storage)
    if current < 3:
        _cols = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'geographic_features'"
            ).fetchall()
        }
        if "geojson" not in _cols:
            conn.execute(
                "ALTER TABLE geographic_features ADD COLUMN geojson TEXT"
            )
        logger.debug("Applied migration v2 → v3: geojson column")

    conn.execute(
        "INSERT INTO _schema_version (version) VALUES (?)",
        [_CURRENT_SCHEMA_VERSION],
    )
    logger.debug("Schema stamped at version %d", _CURRENT_SCHEMA_VERSION)


# -- Public API --------------------------------------------------------------

def create_project_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all result tables in a project database.

    Safe to call multiple times (``IF NOT EXISTS``).  Automatically
    applies schema migrations when the database was created by an older
    version of the code.
    """
    conn.execute(_PROJECT_TABLES_SQL)
    conn.execute(_GEOGRAPHIC_TABLES_SQL)
    _ensure_schema(conn)


