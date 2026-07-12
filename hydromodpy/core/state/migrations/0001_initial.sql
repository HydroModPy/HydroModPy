-- =====================================================================
-- HydroModPy global index DDL.
--
-- Machine-wide federation registry that maps known workspaces to their
-- catalog files. Lives under ``<state_dir>/index.duckdb`` (per
-- ``platformdirs``, ``HMP_STATE_HOME`` overridable). One file per machine.
--
-- Federation is LIVE: ``GlobalIndex.refresh_federation`` ATTACHes each
-- workspace catalog READ_ONLY at query time and builds an ``all_simulations``
-- view over their ``v_simulation_summary``. There is no offline snapshot, so
-- the registry holds only the workspaces table (the former
-- ``projects`` / ``simulations_cache`` / ``index_metadata`` /
-- ``v_workspace_health`` snapshot model was never wired and is dropped).
-- =====================================================================

CREATE TABLE workspaces (
    workspace_id    UUID PRIMARY KEY DEFAULT uuid(),
    workspace_uri   VARCHAR NOT NULL UNIQUE,
    label           VARCHAR,
    last_scanned_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_workspaces_uri ON workspaces(workspace_uri);
