-- =====================================================================
-- 0007_simulation_lifecycle
--
-- Identity + lifecycle schema for the simulation-management refactor
-- (plan_refonte_gestion_simulations.md, section 12). Carries the full
-- Phase 1+2 schema surface in one migration so the trash/restore/purge
-- lifecycle needs no follow-up migration.
--
--   * statuses: add 'trashed' (id 8).
--   * simulations: name_stem + version_int (stem-based versioning,
--     replacing the buggy LIKE scan), trashed_at + original_name.
--   * audit_log: widen the event_type CHECK with the lifecycle events
--     (table recreate; hash-chain rows copied verbatim so 0002 stays
--     valid).
--   * sim_notes: append-only timestamped notes (hmp note). The legacy
--     scalar simulations.notes column is kept for now and reconciled in
--     Phase 2 when registration is rewired to write sim_notes.
--   * export_log: one row per emitted export artefact (hmp show / gc).
--   * purge_journal: two-phase crash-safe hard purge. The existing
--     deletions table stays the final GDPR tombstone.
-- =====================================================================

-- ---------------------------------------------------------------------
-- statuses: trashed
-- ---------------------------------------------------------------------
INSERT INTO statuses (id, code) VALUES (8, 'trashed');

-- ---------------------------------------------------------------------
-- simulations: stem versioning + trash columns
-- ---------------------------------------------------------------------
ALTER TABLE simulations ADD COLUMN name_stem     VARCHAR;
ALTER TABLE simulations ADD COLUMN version_int   INTEGER;
ALTER TABLE simulations ADD COLUMN trashed_at    TIMESTAMPTZ;
ALTER TABLE simulations ADD COLUMN original_name VARCHAR;

UPDATE simulations
SET name_stem   = regexp_replace(name, '\.v[0-9]+$', ''),
    version_int = coalesce(try_cast(regexp_extract(name, '\.v([0-9]+)$', 1) AS INTEGER), 1)
WHERE name IS NOT NULL;

CREATE INDEX ix_sim_name_stem ON simulations(project, name_stem, version_int);

-- ---------------------------------------------------------------------
-- audit_log: widen event_type CHECK (DuckDB cannot ALTER a CHECK, so
-- recreate the table copying every column verbatim - prev_hash and
-- chain_hash included - to preserve the 0002 hash chain).
-- ---------------------------------------------------------------------
CREATE TABLE audit_log_v7 (
    event_id    UUID PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    actor       VARCHAR NOT NULL,
    actor_kind  VARCHAR NOT NULL
                CHECK (actor_kind IN ('os_user', 'principal', 'system', 'cli', 'api')),
    event_type  VARCHAR NOT NULL
                CHECK (event_type IN (
                    'sim.register', 'sim.finalize', 'sim.delete',
                    'sim.purge', 'sim.rename', 'sim.tag_add',
                    'sim.tag_remove', 'param.write', 'param.update',
                    'metric.write', 'tracked_file.add',
                    'tracked_file.remove', 'objective.set',
                    'config.replay', 'migrate', 'gc', 'vacuum',
                    'export', 'import',
                    'sim.trash', 'sim.restore',
                    'sim.purge.begin', 'sim.purge.commit',
                    'note.add', 'export.write'
                )),
    sim_id      UUID,
    project     VARCHAR,
    payload     JSON NOT NULL,
    git_commit  VARCHAR,
    hostname    VARCHAR,
    prev_hash   VARCHAR,
    chain_hash  VARCHAR
);

INSERT INTO audit_log_v7
    SELECT event_id, occurred_at, actor, actor_kind, event_type, sim_id,
           project, payload, git_commit, hostname, prev_hash, chain_hash
    FROM audit_log;

DROP TABLE audit_log;
ALTER TABLE audit_log_v7 RENAME TO audit_log;

CREATE INDEX ix_audit_sim        ON audit_log(sim_id);
CREATE INDEX ix_audit_type       ON audit_log(event_type);
CREATE INDEX ix_audit_time       ON audit_log(occurred_at DESC);
CREATE INDEX ix_audit_actor      ON audit_log(actor);
CREATE INDEX ix_audit_chain_hash ON audit_log(chain_hash);

-- ---------------------------------------------------------------------
-- sim_notes: append-only run notes
-- ---------------------------------------------------------------------
CREATE TABLE sim_notes (
    note_id  UUID PRIMARY KEY,
    sim_id   UUID NOT NULL,
    note     VARCHAR NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    added_by VARCHAR
);

CREATE INDEX ix_sim_notes_sim ON sim_notes(sim_id);

-- ---------------------------------------------------------------------
-- export_log: one row per emitted export artefact
-- ---------------------------------------------------------------------
CREATE TABLE export_log (
    export_id  UUID PRIMARY KEY,
    sim_id     UUID NOT NULL,
    kind       VARCHAR NOT NULL,
    rel_path   VARCHAR NOT NULL,
    bytes      BIGINT,
    sha256     VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_export_log_sim ON export_log(sim_id);

-- ---------------------------------------------------------------------
-- purge_journal: two-phase crash-safe hard purge
-- ---------------------------------------------------------------------
CREATE TABLE purge_journal (
    sim_id       UUID PRIMARY KEY,
    phase        VARCHAR NOT NULL CHECK (phase IN ('pending', 'rmtree_done')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    requested_by VARCHAR
);
