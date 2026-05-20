-- =====================================================================
-- Audit hash chain (T6.A)
--
-- Each audit_log row gains:
--   * prev_hash: chain_hash of the previous row at insertion time,
--   * chain_hash: SHA-256 of (prev_hash || event_id || event_type
--                  || sim_id || project || payload || occurred_at).
--
-- The chain is sealed at write time by emit_audit_event; this migration
-- only widens the schema. Existing rows keep NULL hashes and are not
-- back-filled (verifying the chain starts at the first row written
-- after the migration).
-- =====================================================================

ALTER TABLE audit_log ADD COLUMN prev_hash  VARCHAR;
ALTER TABLE audit_log ADD COLUMN chain_hash VARCHAR;

CREATE INDEX ix_audit_chain_hash ON audit_log(chain_hash);
