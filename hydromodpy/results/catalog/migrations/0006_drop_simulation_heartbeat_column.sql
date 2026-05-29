-- =====================================================================
-- Drop legacy simulations.last_heartbeat column
--
-- Runtime heartbeats are now append-only workflow_events rows. The
-- v_workflow_heartbeats view is the supported liveness source for GC,
-- doctor, and diagnostics.
-- =====================================================================

DROP VIEW IF EXISTS v_best_per_project;
DROP VIEW IF EXISTS v_simulation_summary;
DROP VIEW IF EXISTS v_metrics_pivot;

DROP INDEX IF EXISTS ix_sim_project;
DROP INDEX IF EXISTS ix_sim_solver;
DROP INDEX IF EXISTS ix_sim_status;
DROP INDEX IF EXISTS ix_sim_created_at;
DROP INDEX IF EXISTS ix_sim_config_hash;
DROP INDEX IF EXISTS ix_sim_geo_fp;
DROP INDEX IF EXISTS ix_sim_study_area;
DROP INDEX IF EXISTS ix_sim_scientific_obj;
DROP INDEX IF EXISTS ix_sim_principal;

ALTER TABLE simulations DROP COLUMN IF EXISTS last_heartbeat;

CREATE INDEX ix_sim_project        ON simulations(project);
CREATE INDEX ix_sim_solver         ON simulations(solver_id);
CREATE INDEX ix_sim_status         ON simulations(status_id);
CREATE INDEX ix_sim_created_at     ON simulations(created_at DESC);
CREATE INDEX ix_sim_config_hash    ON simulations(config_hash);
CREATE INDEX ix_sim_geo_fp         ON simulations(geographic_fingerprint);
CREATE INDEX ix_sim_study_area     ON simulations(study_area_name);
CREATE INDEX ix_sim_scientific_obj ON simulations(scientific_objective);
CREATE INDEX ix_sim_principal      ON simulations(principal_id);
