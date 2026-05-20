-- =====================================================================
-- Retention policies (T6.A)
--
-- ``retention_policies`` declares how long each ``audit_log.event_type``
-- is kept before the periodic sweep deletes (or pseudonymizes) it. The
-- table is empty by default: the runtime keeps every event forever
-- until a policy is inserted. ``apply_retention`` (see audit.py) iterates
-- over the rows and removes events older than ``retention_days``.
-- =====================================================================

CREATE TABLE retention_policies (
    policy_id      UUID PRIMARY KEY,
    event_type     VARCHAR NOT NULL,
    retention_days INTEGER NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (event_type)
);

CREATE INDEX ix_retention_event ON retention_policies(event_type);
