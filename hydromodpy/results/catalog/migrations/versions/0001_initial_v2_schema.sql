-- =====================================================================
-- HydroModPy v2.0 catalog DDL (initial migration)
--
-- Source of truth: reports_db/99_target_architecture.md sections 4.1-4.13.
-- Notation : DuckDB-portable subset (no PIVOT, no MAP, no QUALIFY).
-- TIMESTAMPTZ, UUID, VARCHAR (alias TEXT), JSON, BOOLEAN.
--
-- Foreign-key strategy in DuckDB:
--   * FK to dim tables (solvers, statuses, flow_regimes, mesh_topologies)
--     are kept because those tables are immutable (insert-only at schema
--     creation, no updates) so the DuckDB FK engine never trips on them.
--   * FK from per-sim tables to ``simulations(sim_id)`` are NOT declared:
--     DuckDB issue duckdb/duckdb#11132 forbids cascading actions and also
--     blocks any UPDATE on a parent row whose children carry a composite
--     PK that references it. Cascading deletes are enforced by the catalog
--     lifecycle layer in Python (results/catalog/lifecycle.py). When the
--     runner moves to SQLAlchemy + Postgres in P5, real FK + ON DELETE
--     CASCADE will be re-introduced at the DDL layer.
--   * Self-FK on ``simulations.parent_sim_id`` is also dropped for the
--     same reason; lineage is enforced by the Python layer.
--
-- UUIDs are generated client-side (uuid v7 recommended) or via the
-- DuckDB ``uuid()`` function which is v4. v7 ordering is opportunistic
-- and not enforced at the DDL layer.
-- =====================================================================

-- =====================================================================
-- Section 4.2 - Dimension tables (replace CHECK enums)
-- =====================================================================

CREATE TABLE solvers (
    id            SMALLINT PRIMARY KEY,
    code          VARCHAR NOT NULL UNIQUE,
    category      VARCHAR NOT NULL
                  CHECK (category IN (
                      'distributed', 'integrated', 'lumped',
                      'transport', 'particle_tracking'
                  )),
    version       VARCHAR
);

INSERT INTO solvers (id, code, category) VALUES
    (1, 'modflow6',     'distributed'),
    (2, 'modflow_nwt',  'distributed'),
    (3, 'boussinesq',   'integrated'),
    (4, 'gr4j',         'lumped'),
    (5, 'mt3dms',       'transport'),
    (6, 'modpath',      'particle_tracking');

CREATE TABLE statuses (
    id            SMALLINT PRIMARY KEY,
    code          VARCHAR NOT NULL UNIQUE
);

INSERT INTO statuses (id, code) VALUES
    (1, 'pending'),
    (2, 'running'),
    (3, 'completed'),
    (4, 'partial'),
    (5, 'failed'),
    (6, 'aborted'),
    (7, 'resumed');

CREATE TABLE flow_regimes (
    id            SMALLINT PRIMARY KEY,
    code          VARCHAR NOT NULL UNIQUE
);

INSERT INTO flow_regimes (id, code) VALUES
    (1, 'steady'),
    (2, 'transient'),
    (3, 'steady_then_transient');

CREATE TABLE mesh_topologies (
    id            SMALLINT PRIMARY KEY,
    code          VARCHAR NOT NULL UNIQUE
                  CHECK (code IN (
                      'structured_2d', 'structured_3d',
                      'unstructured_2d', 'unstructured_3d',
                      'lumped', 'network_1d'
                  ))
);

INSERT INTO mesh_topologies (id, code) VALUES
    (1, 'structured_2d'),
    (2, 'structured_3d'),
    (3, 'unstructured_2d'),
    (4, 'unstructured_3d'),
    (5, 'lumped'),
    (6, 'network_1d');

-- =====================================================================
-- Section 4.10septies - Star schema dimension tables
--   Named with the ``dim_`` prefix to avoid collisions with the fact
--   table ``stations`` (rich observation-station metadata, see below).
-- =====================================================================

CREATE TABLE dim_variables (
    id              SMALLINT PRIMARY KEY,
    code            VARCHAR NOT NULL UNIQUE,
    standard_name   VARCHAR,
    unit            VARCHAR NOT NULL,
    category        VARCHAR NOT NULL
                    CHECK (category IN (
                        'state', 'derived', 'budget',
                        'forcing', 'observation'
                    ))
);

CREATE TABLE dim_stations (
    id              SMALLINT PRIMARY KEY,
    code            VARCHAR NOT NULL UNIQUE,
    name            VARCHAR,
    x_proj          DOUBLE,
    y_proj          DOUBLE,
    crs_epsg        INTEGER,
    elevation_m     DOUBLE,
    network         VARCHAR,
    metadata        JSON
);

CREATE TABLE dim_metrics (
    id              SMALLINT PRIMARY KEY,
    code            VARCHAR NOT NULL UNIQUE,
    unit            VARCHAR NOT NULL,
    higher_is_better BOOLEAN,
    physical_min    DOUBLE,
    physical_max    DOUBLE
);

CREATE TABLE dim_projects (
    id              SMALLINT PRIMARY KEY,
    slug            VARCHAR NOT NULL UNIQUE,
    name            VARCHAR,
    root_relative   VARCHAR NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE dim_study_areas (
    id              SMALLINT PRIMARY KEY,
    code            VARCHAR NOT NULL UNIQUE,
    name            VARCHAR,
    bbox_xmin       DOUBLE,
    bbox_ymin       DOUBLE,
    bbox_xmax       DOUBLE,
    bbox_ymax       DOUBLE,
    crs_epsg        INTEGER
);

-- =====================================================================
-- stations (rich observation-station metadata, keyed by code+variable)
-- =====================================================================

CREATE TABLE stations (
    station_id      VARCHAR NOT NULL,
    variable_type   VARCHAR NOT NULL,
    name            VARCHAR,
    latitude        DOUBLE,
    longitude       DOUBLE,
    elevation       DOUBLE,
    source          VARCHAR,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    first_valid     DATE,
    last_valid      DATE,
    metadata        JSON,
    PRIMARY KEY (station_id, variable_type)
);

CREATE INDEX ix_stations_variable ON stations(variable_type);
CREATE INDEX ix_stations_active   ON stations(active);

-- =====================================================================
-- Section 4.3 - simulations (solver-agnostic)
-- =====================================================================

CREATE TABLE simulations (
    sim_id                  UUID PRIMARY KEY,
    name                    VARCHAR,
    project                 VARCHAR NOT NULL,
    solver_id               SMALLINT NOT NULL REFERENCES solvers(id),
    status_id               SMALLINT NOT NULL REFERENCES statuses(id) DEFAULT 1,
    flow_regime_id          SMALLINT REFERENCES flow_regimes(id),
    mesh_topology_id        SMALLINT REFERENCES mesh_topologies(id),
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
    zarr_path               VARCHAR NOT NULL,
    zarr_packed             BOOLEAN NOT NULL DEFAULT FALSE,
    storage_basename        VARCHAR NOT NULL,
    geographic_fingerprint  VARCHAR,
    duration_s              DOUBLE,
    started_at              TIMESTAMPTZ,
    ended_at                TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    notes                   VARCHAR,
    description             VARCHAR,
    scientific_objective    VARCHAR,
    contact_email           VARCHAR,
    doi                     VARCHAR,
    study_area_name         VARCHAR,
    outlet_x                DOUBLE,
    outlet_y                DOUBLE,
    principal_id            VARCHAR,
    last_heartbeat          TIMESTAMPTZ,
    UNIQUE (project, name),
    CONSTRAINT ck_sim_period CHECK (period_end IS NULL OR period_start IS NULL OR period_end >= period_start),
    CONSTRAINT ck_sim_bbox_x CHECK (bbox_xmax IS NULL OR bbox_xmin IS NULL OR bbox_xmax >= bbox_xmin),
    CONSTRAINT ck_sim_bbox_y CHECK (bbox_ymax IS NULL OR bbox_ymin IS NULL OR bbox_ymax >= bbox_ymin)
);

CREATE INDEX ix_sim_project         ON simulations(project);
CREATE INDEX ix_sim_solver          ON simulations(solver_id);
CREATE INDEX ix_sim_status          ON simulations(status_id);
CREATE INDEX ix_sim_created_at      ON simulations(created_at DESC);
CREATE INDEX ix_sim_config_hash     ON simulations(config_hash);
CREATE INDEX ix_sim_geo_fp          ON simulations(geographic_fingerprint);
CREATE INDEX ix_sim_study_area      ON simulations(study_area_name);
CREATE INDEX ix_sim_scientific_obj  ON simulations(scientific_objective);
CREATE INDEX ix_sim_principal       ON simulations(principal_id);
CREATE INDEX ix_sim_heartbeat       ON simulations(last_heartbeat);

-- =====================================================================
-- Section 4.4 - parameters (with FK + valid_from for point-in-time)
-- =====================================================================

CREATE TABLE parameters (
    sim_id          UUID NOT NULL,
    param_name      VARCHAR NOT NULL,
    zone_id         VARCHAR NOT NULL DEFAULT '__global__',
    value           DOUBLE,
    unit            VARCHAR,
    parameterization VARCHAR DEFAULT 'uniform',
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (sim_id, param_name, zone_id)
);

CREATE INDEX ix_param_name        ON parameters(param_name);
CREATE INDEX ix_param_sim         ON parameters(sim_id);
CREATE INDEX ix_param_valid_from  ON parameters(valid_from DESC);

-- =====================================================================
-- Section 4.5 - metrics (FK + valid_from + secondary indexes)
-- =====================================================================

CREATE TABLE metrics (
    sim_id          UUID NOT NULL,
    station_id      VARCHAR NOT NULL DEFAULT '__outlet__',
    variable        VARCHAR NOT NULL DEFAULT 'head',
    metric_name     VARCHAR NOT NULL,
    value           DOUBLE,
    n_samples       INTEGER,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (sim_id, station_id, variable, metric_name)
);

CREATE INDEX ix_metrics_sim_metric    ON metrics(sim_id, metric_name);
CREATE INDEX ix_metrics_metric_value  ON metrics(metric_name, value DESC);
CREATE INDEX ix_metric_valid_from     ON metrics(valid_from DESC);

-- =====================================================================
-- Section 4.6 - metric_definitions (reference metadata for metrics)
-- =====================================================================

CREATE TABLE metric_definitions (
    metric_name        VARCHAR PRIMARY KEY,
    unit               VARCHAR NOT NULL,
    higher_is_better   BOOLEAN,
    physical_min       DOUBLE,
    physical_max       DOUBLE,
    role               VARCHAR NOT NULL
                       CHECK (role IN ('feature', 'target', 'diagnostic')),
    description        VARCHAR,
    metric_references  VARCHAR
);

INSERT INTO metric_definitions (
    metric_name, unit, higher_is_better,
    physical_min, physical_max, role, description
) VALUES
    ('nse',   '1', TRUE,  NULL, 1.0,  'diagnostic', 'Nash-Sutcliffe Efficiency'),
    ('kge',   '1', TRUE,  NULL, 1.0,  'diagnostic', 'Kling-Gupta Efficiency'),
    ('rmse',  'm', FALSE, 0.0,  NULL, 'diagnostic', 'Root-Mean-Square Error'),
    ('r2',    '1', TRUE,  NULL, 1.0,  'diagnostic', 'Coefficient of determination'),
    ('mae',   'm', FALSE, 0.0,  NULL, 'diagnostic', 'Mean Absolute Error'),
    ('mse',   '1', FALSE, 0.0,  NULL, 'diagnostic', 'Mean Squared Error'),
    ('bias',  'm', NULL,  NULL, NULL, 'diagnostic', 'Mean bias'),
    ('pbias', '%', NULL,  NULL, NULL, 'diagnostic', 'Percent bias');

-- =====================================================================
-- Section 4.7 - runs_environment (solver-agnostic, no mf6_* columns)
-- =====================================================================

CREATE TABLE runs_environment (
    sim_id                  UUID PRIMARY KEY,
    python_version          VARCHAR,
    hydromodpy_version      VARCHAR,
    platform                VARCHAR,
    hostname                VARCHAR,
    user_name               VARCHAR,
    cpu_info                JSON,
    memory_gb               DOUBLE,
    git_commit              VARCHAR,
    git_dirty               BOOLEAN,
    project_git_commit      VARCHAR,
    solver_name             VARCHAR,
    solver_binary_path      VARCHAR,
    solver_binary_sha256    VARCHAR,
    solver_version_text     VARCHAR,
    additional_solvers      JSON,
    conda_env_hash          VARCHAR,
    env_packages            JSON,
    rng_seed                BIGINT,
    principal_id            VARCHAR,
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_runs_env_solver   ON runs_environment(solver_name);
CREATE INDEX ix_runs_env_versions ON runs_environment(hydromodpy_version, solver_version_text);

-- =====================================================================
-- Section 13.1 - provenance (per-sim source tracking)
-- =====================================================================

CREATE TABLE provenance (
    sim_id          UUID NOT NULL,
    variable        VARCHAR NOT NULL,
    source_type     VARCHAR
                    CHECK (source_type IS NULL OR source_type IN (
                        'http_api', 'custom_file', 'data_manager',
                        'derived', 'cache'
                    )),
    source_ref      VARCHAR NOT NULL,
    source_sha256   VARCHAR,
    payload_sha256  VARCHAR,
    loader_name     VARCHAR,
    loader_version  VARCHAR,
    fetched_at      TIMESTAMPTZ,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    n_records       BIGINT,
    stats           JSON,
    license         VARCHAR,
    data_provider   VARCHAR,
    etag            VARCHAR,
    last_modified   TIMESTAMPTZ,
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (sim_id, variable, source_ref)
);

CREATE INDEX ix_prov_sha256     ON provenance(source_sha256);
CREATE INDEX ix_prov_valid_from ON provenance(valid_from DESC);

-- =====================================================================
-- observations table (cross-sim, station-keyed time series)
-- Required for valid_from ALTER referenced in section 4.10octies.
-- =====================================================================

CREATE TABLE observations (
    station_id      VARCHAR NOT NULL,
    variable_type   VARCHAR NOT NULL,
    datetime        TIMESTAMPTZ NOT NULL,
    value           DOUBLE,
    unit            VARCHAR,
    quality         VARCHAR,
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (station_id, variable_type, datetime)
);

CREATE INDEX ix_observations_datetime  ON observations(datetime);
CREATE INDEX ix_obs_valid_from         ON observations(valid_from DESC);

-- =====================================================================
-- observation_points (per-sim virtual observation cells)
-- =====================================================================

CREATE TABLE observation_points (
    sim_id      UUID NOT NULL,
    station_id  VARCHAR NOT NULL,
    x           DOUBLE NOT NULL,
    y           DOUBLE NOT NULL,
    cell_id     INTEGER NOT NULL,
    layer       INTEGER NOT NULL DEFAULT 0,
    crs_wkt     VARCHAR NOT NULL,
    crs_epsg    INTEGER,
    PRIMARY KEY (sim_id, station_id)
);

CREATE INDEX ix_obs_points_cell ON observation_points(sim_id, cell_id);

-- =====================================================================
-- Section 4.8 - audit_log (event sourcing)
-- =====================================================================

CREATE TABLE audit_log (
    event_id      UUID PRIMARY KEY,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    actor         VARCHAR NOT NULL,
    actor_kind    VARCHAR NOT NULL
                  CHECK (actor_kind IN ('os_user', 'principal', 'system', 'cli', 'api')),
    event_type    VARCHAR NOT NULL
                  CHECK (event_type IN (
                      'sim.register', 'sim.finalize', 'sim.delete',
                      'sim.purge', 'sim.rename', 'sim.tag_add',
                      'sim.tag_remove', 'param.write', 'param.update',
                      'metric.write', 'tracked_file.add',
                      'tracked_file.remove', 'objective.set',
                      'config.replay', 'migrate', 'gc', 'vacuum',
                      'export', 'import'
                  )),
    sim_id        UUID,
    project       VARCHAR,
    payload       JSON NOT NULL,
    git_commit    VARCHAR,
    hostname      VARCHAR
);

CREATE INDEX ix_audit_sim   ON audit_log(sim_id);
CREATE INDEX ix_audit_type  ON audit_log(event_type);
CREATE INDEX ix_audit_time  ON audit_log(occurred_at DESC);
CREATE INDEX ix_audit_actor ON audit_log(actor);

-- =====================================================================
-- Section 4.9 - deletions (GDPR tombstones)
-- =====================================================================

CREATE TABLE deletions (
    sim_id          UUID PRIMARY KEY,
    deleted_at      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    deleted_by      VARCHAR,
    reason          VARCHAR,
    components      JSON,
    sha256_snapshot VARCHAR
);

-- =====================================================================
-- tracked_files (workspace-relative file manifest, per-sim)
-- =====================================================================

CREATE TABLE tracked_files (
    sim_id          UUID NOT NULL,
    role            VARCHAR NOT NULL,
    category        VARCHAR NOT NULL,
    original_path   VARCHAR NOT NULL,
    canonical_path  VARCHAR NOT NULL,
    sha256          VARCHAR NOT NULL,
    size_bytes      BIGINT NOT NULL,
    portable        BOOLEAN NOT NULL DEFAULT TRUE,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (sim_id, role, canonical_path)
);

CREATE INDEX ix_tracked_files_sha ON tracked_files(sha256);

-- =====================================================================
-- geographic_features (per-sim GeoParquet pointers)
-- =====================================================================

CREATE TABLE geographic_features (
    sim_id          UUID NOT NULL,
    feature_name    VARCHAR NOT NULL,
    geometry_kind   VARCHAR
                    CHECK (geometry_kind IS NULL OR geometry_kind IN (
                        'point', 'linestring', 'polygon', 'multipolygon'
                    )),
    crs_wkt         VARCHAR,
    geoparquet_path VARCHAR,
    properties      JSON,
    PRIMARY KEY (sim_id, feature_name)
);

-- =====================================================================
-- geographic_metadata (typed sim-level KV)
-- =====================================================================

CREATE TABLE geographic_metadata (
    sim_id          UUID NOT NULL,
    key             VARCHAR NOT NULL,
    value           VARCHAR,
    value_type      VARCHAR NOT NULL DEFAULT 'string'
                    CHECK (value_type IN ('double', 'int', 'string', 'bool')),
    unit            VARCHAR,
    PRIMARY KEY (sim_id, key)
);

-- =====================================================================
-- parquet_files manifest (workspace-relative)
-- =====================================================================

CREATE TABLE parquet_files (
    sim_id          UUID NOT NULL,
    path            VARCHAR NOT NULL,
    view_name       VARCHAR NOT NULL,
    n_rows          BIGINT,
    bytes           BIGINT,
    sha256          VARCHAR,
    written_at      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (sim_id, view_name)
);

CREATE INDEX ix_parquet_files_path ON parquet_files(path);

-- =====================================================================
-- tags (sim-level free-form labels)
-- =====================================================================

CREATE TABLE tags (
    sim_id      UUID NOT NULL,
    tag         VARCHAR NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    added_by    VARCHAR,
    PRIMARY KEY (sim_id, tag)
);

CREATE INDEX ix_tags_tag ON tags(tag);

-- =====================================================================
-- Section 4.11 - calibration_sessions (enriched)
-- =====================================================================

CREATE TABLE calibration_sessions (
    session_id              UUID PRIMARY KEY,
    project                 VARCHAR NOT NULL,
    method                  VARCHAR NOT NULL,
    objective_name          VARCHAR NOT NULL,
    n_iterations            INTEGER NOT NULL DEFAULT 0,
    best_sim_id             UUID,
    best_objective          DOUBLE,
    best_params_hash        VARCHAR,
    config                  JSON NOT NULL,
    config_path             VARCHAR,
    seed                    BIGINT,
    hydromodpy_version      VARCHAR,
    python_version          VARCHAR,
    hostname                VARCHAR,
    optimizer_storage       VARCHAR,
    optimizer_state_blob    BLOB,
    wallclock_breakdown     JSON,
    started_at              TIMESTAMPTZ NOT NULL,
    ended_at                TIMESTAMPTZ,
    duration_s              DOUBLE,
    status_id               SMALLINT NOT NULL REFERENCES statuses(id) DEFAULT 1,
    error_message           VARCHAR,
    last_resumed_at         TIMESTAMPTZ,
    n_resumes               INTEGER DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_cal_session_project ON calibration_sessions(project);
CREATE INDEX ix_cal_session_status  ON calibration_sessions(status_id);
CREATE INDEX ix_cal_session_started ON calibration_sessions(started_at DESC);

-- =====================================================================
-- calibration_iterations (per-iteration trace)
-- =====================================================================

CREATE TABLE calibration_iterations (
    session_id      UUID NOT NULL,
    iteration       INTEGER NOT NULL,
    sim_id          UUID,
    params_hash     VARCHAR,
    parameters      JSON NOT NULL,
    objective_value DOUBLE,
    metrics         JSON,
    status          VARCHAR DEFAULT 'completed'
                    CHECK (status IN (
                        'completed', 'diverged', 'timeout',
                        'crashed', 'cached'
                    )),
    from_cache      BOOLEAN DEFAULT FALSE,
    duration_s      DOUBLE,
    PRIMARY KEY (session_id, iteration)
);

CREATE INDEX ix_cal_iter_sim  ON calibration_iterations(sim_id);
CREATE INDEX ix_cal_iter_hash ON calibration_iterations(params_hash);

-- =====================================================================
-- Section 4.10sexies - workflow_steps (fusion of steps_ledger)
-- =====================================================================

CREATE TABLE workflow_steps (
    step_id         UUID PRIMARY KEY,
    run_id          VARCHAR NOT NULL,
    step_order      INTEGER NOT NULL,
    step_name       VARCHAR NOT NULL,
    status_id       SMALLINT NOT NULL REFERENCES statuses(id) DEFAULT 1,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    duration_s      DOUBLE,
    checkpoint_path VARCHAR,
    inputs_hash     VARCHAR,
    outputs_hash    VARCHAR,
    error_message   VARCHAR,
    UNIQUE (run_id, step_order)
);

CREATE INDEX ix_wf_run_id ON workflow_steps(run_id);
CREATE INDEX ix_wf_status ON workflow_steps(status_id);
