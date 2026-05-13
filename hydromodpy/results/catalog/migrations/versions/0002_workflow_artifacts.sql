-- =====================================================================
-- 0002 - workflow_steps artifact tracking
--   Adds a JSON column to record workspace-relative artifact paths
--   produced by each pipeline step. Replaces the pickle-based
--   CheckpointStore as the source of truth for resume decisions.
-- =====================================================================

ALTER TABLE workflow_steps ADD COLUMN artifact_uris JSON;
