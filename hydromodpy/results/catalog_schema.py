"""DuckDB schema for the HydroModPy simulation catalog.

Clean-slate schema (phase P02): 12 core tables with normalized primary keys,
``TIMESTAMPTZ`` time columns, a JSON ``config_snapshot`` for full-config
reproducibility, and a ``geographic_fingerprint`` column that ties each
simulation to the workspace-level content-addressable geographic cache
(see :mod:`hydromodpy.results.geographic_cache`).

This module defines only DDL and helpers; it does not track historical schema
versions. Each major release starts from a fresh schema. Migration principles
for post-P13 evolutions are documented in
``docs/developers/schema_evolution.md``.

Note on referential integrity: per-sim tables carry ``sim_id UUID NOT NULL``
columns but **no** ``FOREIGN KEY`` clause. DuckDB's foreign-key engine does
not implement ``ON DELETE CASCADE`` and refuses ``UPDATE`` on a parent row
when child rows with composite primary keys still reference it (issue
#duckdb/duckdb#11132 family). The catalog's :py:meth:`SimulationCatalog.delete`
method removes per-sim rows explicitly, which gives equivalent semantics
without the engine bug.
"""

from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)

HOMOGENEOUS_ZONE = "_homogeneous"
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
    parent_sim_id           UUID,
    lineage_kind            VARCHAR,
    zarr_path               VARCHAR,
    zarr_packed             BOOLEAN NOT NULL DEFAULT FALSE,
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
CREATE INDEX IF NOT EXISTS ix_sim_mesh_hash ON simulations(mesh_hash);
CREATE INDEX IF NOT EXISTS ix_sim_geo_fp ON simulations(geographic_fingerprint);
"""

# ---------------------------------------------------------------------------
#  Parameters, metrics, timeseries, budgets, mass_balance
# ---------------------------------------------------------------------------

_PARAMETERS_DDL = """
CREATE TABLE IF NOT EXISTS parameters (
    sim_id           UUID NOT NULL,
    param_name       VARCHAR NOT NULL,
    zone_id          VARCHAR NOT NULL DEFAULT '_homogeneous',
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

_TIMESERIES_DDL = """
CREATE TABLE IF NOT EXISTS timeseries (
    sim_id     UUID NOT NULL,
    station_id VARCHAR NOT NULL,
    variable   VARCHAR NOT NULL,
    datetime   TIMESTAMPTZ NOT NULL,
    value      DOUBLE,
    unit       VARCHAR,
    qflag      VARCHAR DEFAULT 'simulated',
    PRIMARY KEY (sim_id, station_id, variable, datetime)
);
CREATE INDEX IF NOT EXISTS ix_ts_lookup
    ON timeseries(sim_id, station_id, variable, datetime);
CREATE INDEX IF NOT EXISTS ix_ts_cross_sim
    ON timeseries(station_id, variable, datetime);
"""

_BUDGETS_DDL = """
CREATE TABLE IF NOT EXISTS budgets (
    sim_id    UUID NOT NULL,
    timestep  INTEGER NOT NULL CHECK (timestep >= 0),
    zone_id   VARCHAR NOT NULL DEFAULT '__global__',
    component VARCHAR NOT NULL
        CHECK (component IN (
            'recharge', 'drain', 'river', 'ghb', 'chd', 'well',
            'storage', 'constant_head', 'specified_flow',
            'evapotranspiration', 'seepage'
        )),
    flux_in   DOUBLE NOT NULL DEFAULT 0.0,
    flux_out  DOUBLE NOT NULL DEFAULT 0.0,
    unit      VARCHAR NOT NULL DEFAULT 'm3/d',
    PRIMARY KEY (sim_id, timestep, zone_id, component)
);
CREATE INDEX IF NOT EXISTS ix_budgets_component ON budgets(component);
"""

_MASS_BALANCE_DDL = """
CREATE TABLE IF NOT EXISTS mass_balance (
    sim_id        UUID NOT NULL,
    timestep      INTEGER NOT NULL,
    total_in      DOUBLE NOT NULL,
    total_out     DOUBLE NOT NULL,
    storage_in    DOUBLE NOT NULL,
    storage_out   DOUBLE NOT NULL,
    percent_error DOUBLE NOT NULL,
    unit          VARCHAR NOT NULL DEFAULT 'm3/d',
    PRIMARY KEY (sim_id, timestep)
);
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

# ---------------------------------------------------------------------------
#  Public constants and entry points
# ---------------------------------------------------------------------------

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
    "geographic_features",
    "geographic_metadata",
)

_ALL_DDL: tuple[str, ...] = (
    _SIMULATIONS_DDL,
    _PARAMETERS_DDL,
    _METRICS_DDL,
    _TIMESERIES_DDL,
    _BUDGETS_DDL,
    _MASS_BALANCE_DDL,
    _OBSERVATION_POINTS_DDL,
    _PROVENANCE_DDL,
    _CALIBRATION_SESSIONS_DDL,
    _CALIBRATION_ITERATIONS_DDL,
    _GEOGRAPHIC_FEATURES_DDL,
    _GEOGRAPHIC_METADATA_DDL,
)


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the 12 catalog tables if they do not already exist.

    Idempotent: repeated calls on the same connection are safe. The function
    does not register a schema version — the whole catalog follows a
    clean-slate policy for the current release. See
    ``docs/developers/schema_evolution.md`` for future-proof evolution rules.
    """
    for ddl in _ALL_DDL:
        conn.execute(ddl)
    logger.debug("DuckDB catalog schema ensured (%d tables)", len(TABLE_NAMES))
