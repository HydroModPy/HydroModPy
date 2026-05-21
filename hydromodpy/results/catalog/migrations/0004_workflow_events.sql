-- =====================================================================
-- workflow_events (event-stream companion to workflow_steps)
--
-- The ledger ``workflow_steps`` keeps one row per step lifecycle (final
-- state + hashes). ``workflow_events`` records every transient signal
-- emitted while a run is live: heartbeats, step start/end markers,
-- cancellation, custom logs. This split lets ``hmp gc`` and
-- ``hmp doctor`` derive ``last_heartbeat`` from a MAX(ts) view instead
-- of mutating ``simulations``.
--
-- Append-only by contract: no UPDATE statements are issued. Rows are
-- pruned by GDPR retention policies (see ``hmp retain``).
-- =====================================================================

CREATE SEQUENCE IF NOT EXISTS seq_workflow_events START 1;

CREATE TABLE workflow_events (
    event_id    INTEGER PRIMARY KEY DEFAULT nextval('seq_workflow_events'),
    run_id      VARCHAR NOT NULL,
    step_name   VARCHAR NOT NULL,
    event_type  VARCHAR NOT NULL
                CHECK (event_type IN (
                    'step_start', 'step_end', 'heartbeat',
                    'cancel', 'log'
                )),
    payload     JSON,
    ts          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_wf_events_run_id     ON workflow_events(run_id);
CREATE INDEX ix_wf_events_type       ON workflow_events(event_type);
CREATE INDEX ix_wf_events_run_step   ON workflow_events(run_id, step_name);
CREATE INDEX ix_wf_events_ts         ON workflow_events(ts);

-- Convenience view: per-sim heartbeat timestamp derived from the
-- event-stream, replacing a direct read of ``simulations.last_heartbeat``.
CREATE VIEW v_workflow_heartbeats AS
SELECT
    run_id,
    MAX(ts) AS last_heartbeat
FROM workflow_events
WHERE event_type = 'heartbeat'
GROUP BY run_id;
