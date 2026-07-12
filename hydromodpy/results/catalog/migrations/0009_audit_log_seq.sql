-- =====================================================================
-- 0009_audit_log_seq
--
-- The audit hash-chain ordered rows by (occurred_at, event_id). But
-- occurred_at is frozen to the transaction start (DuckDB pins
-- current_timestamp per transaction) and event_id is a random uuid4, so
-- two audit rows written in one transaction (register + per-tag
-- sim.tag_add, or a replace-collision plus a tag) got an ambiguous order.
-- verify_chain could then replay them in a different order than the chain
-- was built and report a fork on an untampered catalog.
--
-- Add a monotonic per-row sequence and order the chain by it. Existing
-- rows are backfilled in their historical (occurred_at, event_id) order so
-- an already-written chain keeps verifying after the migration.
-- =====================================================================

ALTER TABLE audit_log ADD COLUMN seq BIGINT;

UPDATE audit_log
SET seq = ordered.rn
FROM (
    SELECT event_id, row_number() OVER (ORDER BY occurred_at, event_id) AS rn
    FROM audit_log
) AS ordered
WHERE audit_log.event_id = ordered.event_id;
