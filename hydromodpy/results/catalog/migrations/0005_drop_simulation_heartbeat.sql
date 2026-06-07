-- =====================================================================
-- Drop simulations indexes before heartbeat column removal
--
-- Workflow liveness is now represented exclusively by workflow_events
-- and the v_workflow_heartbeats view introduced in migration 0004.
-- DuckDB refuses ALTER TABLE DROP COLUMN while any index depends on the
-- table. The column drop and index recreation live in migration 0006.
-- =====================================================================

DROP INDEX IF EXISTS ix_sim_project;
DROP INDEX IF EXISTS ix_sim_solver;
DROP INDEX IF EXISTS ix_sim_status;
DROP INDEX IF EXISTS ix_sim_created_at;
DROP INDEX IF EXISTS ix_sim_config_hash;
DROP INDEX IF EXISTS ix_sim_geo_fp;
DROP INDEX IF EXISTS ix_sim_study_area;
DROP INDEX IF EXISTS ix_sim_scientific_obj;
DROP INDEX IF EXISTS ix_sim_principal;
DROP INDEX IF EXISTS ix_sim_heartbeat;
