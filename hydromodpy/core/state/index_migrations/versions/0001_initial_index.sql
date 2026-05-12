CREATE TABLE workspaces (
    workspace_id    UUID PRIMARY KEY DEFAULT uuid(),
    workspace_uri   VARCHAR NOT NULL UNIQUE,
    label           VARCHAR,
    last_scanned_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE index_metadata (
    scanned_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    schema_version INTEGER NOT NULL
);

CREATE INDEX ix_workspaces_uri ON workspaces(workspace_uri);
