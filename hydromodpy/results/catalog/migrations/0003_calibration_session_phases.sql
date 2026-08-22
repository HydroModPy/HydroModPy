-- =====================================================================
-- Calibration session phase chaining
-- =====================================================================
--
-- A calibration is often run in phases: a coarse sweep, then a refinement
-- seeded by its result. Each phase is its own session, so without these
-- columns the index shows unrelated calibrations and cannot say which one
-- continues which.
--
-- The chain is written to sessions/<name>/session.json first and mirrored
-- here, so `hmp catalog reindex` restores it. Nothing a session needs in
-- order to be read or compared lives only in SQL.
--
-- parent_session_id and root_session_id are UUID, the type
-- calibration_sessions.session_id already uses. They hold a session id, so
-- they must join against it without a cast, and the rebuild coerces every
-- session id through UUID anyway. VARCHAR would make the join implicit and
-- let a value that is not a session id in.
--
-- No FOREIGN KEY: a parent session may be garbage-collected while the child
-- keeps the id of the phase it continued, and the index is rebuilt one
-- session directory at a time in no guaranteed order.

ALTER TABLE calibration_sessions ADD COLUMN parent_session_id UUID;
ALTER TABLE calibration_sessions ADD COLUMN root_session_id   UUID;
ALTER TABLE calibration_sessions ADD COLUMN phase_name        VARCHAR;
ALTER TABLE calibration_sessions ADD COLUMN phase_index       INTEGER;

CREATE INDEX ix_cal_session_parent ON calibration_sessions(parent_session_id);
CREATE INDEX ix_cal_session_root   ON calibration_sessions(root_session_id);
