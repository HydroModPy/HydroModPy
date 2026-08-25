-- =====================================================================
-- Drop retention_policies (audit_log retention sweep)
-- =====================================================================
--
-- The table was declared by the initial schema and read by an audit purge
-- verb, but no code path ever inserted a row: the sweep had nothing to
-- apply and always reported "no retention policies registered".
--
-- Arming it would have been worse than leaving it empty. audit_log is a
-- hash chain: each row commits to the previous one, and `hmp audit verify`
-- replays the whole chain. A per-event-type age sweep deletes rows from the
-- middle of that chain, so the first applied policy would have broken
-- verification permanently. Tamper-evidence is the only reason the table
-- exists; trading it for a few kilobytes is not a trade worth offering.
--
-- The verb (`hmp audit prune`) and its API entry point go with it.

DROP INDEX IF EXISTS ix_retention_event;

DROP TABLE IF EXISTS retention_policies;
