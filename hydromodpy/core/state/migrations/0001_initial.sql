-- =====================================================================
-- HydroModPy V1 global index DDL (initial migration)
--
-- Machine-wide federation registry: maps known workspaces to their
-- catalog files, and snapshots a denormalised view of every simulation
-- for offline queries.
--
-- Lives under ``<state_dir>/index.duckdb`` (per ``platformdirs``,
-- ``HMP_STATE_HOME`` overridable). One file per machine.
--
-- Tables
--   * ``workspaces`` -- one row per registered workspace URI.
--   * ``projects``   -- one row per project under a workspace.
--   * ``simulations_cache`` -- denormalised snapshot of every sim,
--     refreshed by ``GlobalIndex.refresh()``. Carries the solver code as
--     a flat text column so ``find(solver=...)`` no longer dereferences
--     a foreign key (rapport 10 §3, C.1).
--   * ``index_metadata`` -- single-row registry metadata.
-- =====================================================================


-- =====================================================================
-- workspaces (registered workspace roots)
-- =====================================================================

CREATE TABLE workspaces (
    workspace_id    UUID PRIMARY KEY DEFAULT uuid(),
    workspace_uri   VARCHAR NOT NULL UNIQUE,
    label           VARCHAR,
    last_scanned_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    status          VARCHAR NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'ok', 'unreachable', 'schema_mismatch', 'corrupt'))
);

CREATE INDEX ix_workspaces_uri ON workspaces(workspace_uri);

-- =====================================================================
-- projects (cross-workspace project registry)
-- =====================================================================

CREATE TABLE projects (
    project_id    UUID PRIMARY KEY DEFAULT uuid(),
    workspace_id  UUID NOT NULL REFERENCES workspaces(workspace_id),
    slug          VARCHAR NOT NULL,
    name          VARCHAR,
    root_relative VARCHAR NOT NULL,
    n_simulations INTEGER NOT NULL DEFAULT 0,
    last_run_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (workspace_id, slug)
);

CREATE INDEX ix_projects_slug      ON projects(slug);
CREATE INDEX ix_projects_workspace ON projects(workspace_id);

-- =====================================================================
-- simulations_cache (offline-friendly snapshot)
--   ``solver`` and ``status`` are denormalised text codes so
--   ``GlobalIndex.find(solver="modflow6")`` filters on a column that
--   exists. Snapshotted from ``v_simulation_summary`` of each attached
--   catalog by ``GlobalIndex.refresh()``.
-- =====================================================================

CREATE TABLE simulations_cache (
    workspace_id         UUID NOT NULL REFERENCES workspaces(workspace_id),
    sim_id               UUID NOT NULL,
    name                 VARCHAR,
    project              VARCHAR NOT NULL,
    solver               VARCHAR,
    solver_category      VARCHAR,
    status               VARCHAR,
    flow_regime          VARCHAR,
    mesh_topology        VARCHAR,
    study_area_name      VARCHAR,
    scientific_objective VARCHAR,
    description          VARCHAR,
    contact_email        VARCHAR,
    principal_id         VARCHAR,
    bbox_xmin            DOUBLE,
    bbox_ymin            DOUBLE,
    bbox_xmax            DOUBLE,
    bbox_ymax            DOUBLE,
    period_start         TIMESTAMPTZ,
    period_end           TIMESTAMPTZ,
    created_at           TIMESTAMPTZ,
    duration_s           DOUBLE,
    snapshot_taken_at    TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (workspace_id, sim_id)
);

CREATE INDEX ix_simcache_solver        ON simulations_cache(solver);
CREATE INDEX ix_simcache_project       ON simulations_cache(project);
CREATE INDEX ix_simcache_study_area    ON simulations_cache(study_area_name);
CREATE INDEX ix_simcache_status        ON simulations_cache(status);
CREATE INDEX ix_simcache_created_at    ON simulations_cache(created_at DESC);

-- =====================================================================
-- index_metadata (registry-wide bookkeeping)
-- =====================================================================

CREATE TABLE index_metadata (
    scanned_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- =====================================================================
-- v_workspace_health (one row per workspace with summary status)
-- =====================================================================

CREATE VIEW v_workspace_health AS
SELECT
    w.workspace_id,
    w.workspace_uri,
    w.label,
    w.status,
    w.last_scanned_at,
    w.created_at,
    COUNT(DISTINCT p.project_id) AS n_projects,
    COUNT(DISTINCT sc.sim_id)    AS n_simulations,
    MAX(sc.created_at)           AS latest_simulation_at
FROM workspaces w
LEFT JOIN projects          p  ON p.workspace_id  = w.workspace_id
LEFT JOIN simulations_cache sc ON sc.workspace_id = w.workspace_id
GROUP BY w.workspace_id, w.workspace_uri, w.label, w.status,
         w.last_scanned_at, w.created_at;
