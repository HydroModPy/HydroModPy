-- =====================================================================
-- HydroModPy global index DDL.
--
-- Machine-wide federation registry that maps known PROJECTS to their index
-- databases. Lives under ``<state_dir>/index.duckdb`` (per ``platformdirs``,
-- ``HMP_STATE_HOME`` overridable). One file per machine.
--
-- Granularity: one row per project root. A project root is what owns an index
-- database at ``<project>/.hmp/index.duckdb``; a workspace owns none and holds
-- many projects, so it never becomes a row. ``GlobalIndex.register`` expands a
-- workspace root into the project roots it contains.
--
-- Federation is LIVE: ``GlobalIndex.refresh_federation`` ATTACHes each project
-- index READ_ONLY at query time and builds an ``all_simulations`` view over
-- their ``v_simulation_summary``. There is no offline snapshot, so the registry
-- holds only the projects table.
-- =====================================================================

CREATE TABLE projects (
    project_id      UUID PRIMARY KEY DEFAULT uuid(),
    project_uri     VARCHAR NOT NULL UNIQUE,
    label           VARCHAR,
    last_scanned_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_projects_uri ON projects(project_uri);
