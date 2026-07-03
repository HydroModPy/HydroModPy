-- =====================================================================
-- 0008_trash_original_status
--
-- Preserve the pre-trash status so restore() returns a failed/partial run
-- to its real terminal status instead of inferring 'completed' from
-- ended_at. trash() and the replace-collision branch record the current
-- status_id here; restore() reads it back.
-- =====================================================================

ALTER TABLE simulations ADD COLUMN original_status_id INTEGER;
