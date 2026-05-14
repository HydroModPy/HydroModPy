-- =====================================================================
-- 0002 - workflow_steps artifact tracking
--   Adds a JSON column to record workspace-relative artifact paths
--   produced by each pipeline step. Pairs with workflow_steps as the
--   single source of truth for resume decisions.
-- =====================================================================

ALTER TABLE workflow_steps ADD COLUMN artifact_uris JSON;
