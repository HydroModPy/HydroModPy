"""Global registry and federated queries across project catalogs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from hydromodpy.core.io.db_retry import connect_with_retry

CATALOG_FILENAME = "hydromodpy.duckdb"
GLOBAL_INDEX_FILENAME = "index.duckdb"

FEDERATED_TABLES = (
    "simulations",
    "parameters",
    "metrics",
    "calibration_sessions",
    "calibration_iterations",
    "runs_environment",
    "provenance",
    "tracked_files",
    "tags",
)


def global_state_dir() -> Path:
    """Return the user-state directory used by the global catalog index."""
    override = os.environ.get("HYDROMODPY_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state).expanduser().resolve() / "hydromodpy"
    return Path.home().expanduser() / ".local" / "state" / "hydromodpy"


def global_index_path() -> Path:
    """Return the hidden global DuckDB index path."""
    return global_state_dir() / GLOBAL_INDEX_FILENAME


def _quote_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


class CatalogIndex:
    """Hidden registry plus federated SQL views over project DuckDB catalogs."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path is not None else global_index_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = connect_with_retry(str(self.path))
        self._ensure_schema()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> CatalogIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def register_project(
        self,
        *,
        project_root: Path | str,
        catalog_path: Path | str,
        simulations_dir: Path | str | None = None,
        data_dir: Path | str | None = None,
        slug: str | None = None,
    ) -> None:
        """Register or refresh one project catalog in the global index."""
        root = Path(project_root).expanduser().resolve()
        catalog = Path(catalog_path).expanduser().resolve()
        project_slug = slug or root.name
        self._db.execute(
            """
            INSERT INTO projects
                (project_id, project_slug, project_root, catalog_path,
                 simulations_dir, data_dir, active, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, TRUE, now())
            ON CONFLICT (project_root) DO UPDATE SET
                project_slug = EXCLUDED.project_slug,
                catalog_path = EXCLUDED.catalog_path,
                simulations_dir = EXCLUDED.simulations_dir,
                data_dir = EXCLUDED.data_dir,
                active = TRUE,
                last_seen = now()
            """,
            [
                _project_id(root),
                project_slug,
                str(root),
                str(catalog),
                str(Path(simulations_dir).expanduser().resolve()) if simulations_dir else None,
                str(Path(data_dir).expanduser().resolve()) if data_dir else None,
            ],
        )

    def register_workspace(self, workspace_root: Path | str) -> int:
        """Register every project catalog found under ``workspace/projects``."""
        root = Path(workspace_root).expanduser().resolve()
        candidates = _discover_project_catalogs(root)
        for project_root, catalog_path in candidates:
            self.register_project(project_root=project_root, catalog_path=catalog_path)
        return len(candidates)

    def projects(self) -> pd.DataFrame:
        """Return registered projects."""
        return self._db.execute(
            """
            SELECT project_id, project_slug, project_root, catalog_path,
                   simulations_dir, data_dir, active, last_seen
            FROM projects
            WHERE active
            ORDER BY project_slug, project_root
            """
        ).fetchdf()

    def query(self, sql: str) -> pd.DataFrame:
        """Run SQL against federated ``all_*`` views."""
        projects = self.projects()
        conn = duckdb.connect(":memory:")
        try:
            attached = _attach_projects(conn, projects)
            _create_federated_views(conn, attached)
            return conn.execute(sql).fetchdf()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id      VARCHAR PRIMARY KEY,
                project_slug    VARCHAR NOT NULL,
                project_root    VARCHAR NOT NULL UNIQUE,
                catalog_path    VARCHAR NOT NULL,
                simulations_dir VARCHAR,
                data_dir        VARCHAR,
                active          BOOLEAN NOT NULL DEFAULT TRUE,
                last_seen       TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def _project_id(project_root: Path) -> str:
    import hashlib

    digest = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()
    return digest[:16]


def _discover_project_catalogs(workspace_root: Path) -> list[tuple[Path, Path]]:
    projects_dir = workspace_root / "projects"
    candidates: list[tuple[Path, Path]] = []
    if projects_dir.is_dir():
        for project_root in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
            catalog_path = project_root / CATALOG_FILENAME
            if catalog_path.is_file():
                candidates.append((project_root, catalog_path))
        return candidates
    catalog_path = workspace_root / CATALOG_FILENAME
    if catalog_path.is_file():
        candidates.append((workspace_root, catalog_path))
    return candidates


def _attach_projects(
    conn: duckdb.DuckDBPyConnection, projects: pd.DataFrame
) -> list[dict[str, Any]]:
    attached: list[dict[str, Any]] = []
    for idx, row in projects.iterrows():
        catalog_path = Path(str(row["catalog_path"]))
        if not catalog_path.is_file():
            continue
        alias = f"p{idx}"
        try:
            conn.execute(
                f"ATTACH {_quote_literal(catalog_path)} AS {_quote_identifier(alias)} (READ_ONLY)"
            )
        except duckdb.IOException:
            continue
        attached.append(
            {
                "alias": alias,
                "project_id": str(row["project_id"]),
                "project_slug": str(row["project_slug"]),
                "project_root": str(row["project_root"]),
                "catalog_path": str(catalog_path),
            }
        )
    return attached


def _create_federated_views(
    conn: duckdb.DuckDBPyConnection, projects: list[dict[str, Any]]
) -> None:
    for table in FEDERATED_TABLES:
        parts = []
        for project in projects:
            alias = _quote_identifier(project["alias"])
            table_name = _quote_identifier(table)
            if not _table_exists(conn, alias, table_name):
                continue
            parts.append(
                "SELECT "
                f"{_quote_literal(project['project_id'])} AS project_id, "
                f"{_quote_literal(project['project_slug'])} AS project_slug, "
                f"{_quote_literal(project['project_root'])} AS project_path, "
                f"{_quote_literal(project['catalog_path'])} AS catalog_path, "
                f"t.* FROM {alias}.{table_name} AS t"
            )
        if parts:
            view_name = _quote_identifier(f"all_{table}")
            conn.execute(f"CREATE TEMP VIEW {view_name} AS " + " UNION ALL ".join(parts))
        elif table == "simulations":
            conn.execute(
                """
                CREATE TEMP VIEW all_simulations AS
                SELECT
                    NULL::VARCHAR AS project_id,
                    NULL::VARCHAR AS project_slug,
                    NULL::VARCHAR AS project_path,
                    NULL::VARCHAR AS catalog_path,
                    NULL::VARCHAR AS sim_id,
                    NULL::VARCHAR AS name,
                    NULL::VARCHAR AS project,
                    NULL::VARCHAR AS solver,
                    NULL::VARCHAR AS status,
                    NULL::TIMESTAMPTZ AS created_at
                WHERE FALSE
                """
            )
        elif table == "parameters":
            conn.execute(
                """
                CREATE TEMP VIEW all_parameters AS
                SELECT
                    NULL::VARCHAR AS project_id,
                    NULL::VARCHAR AS project_slug,
                    NULL::VARCHAR AS project_path,
                    NULL::VARCHAR AS catalog_path,
                    NULL::VARCHAR AS sim_id,
                    NULL::VARCHAR AS param_name,
                    NULL::VARCHAR AS zone_id,
                    NULL::DOUBLE AS value,
                    NULL::VARCHAR AS unit
                WHERE FALSE
                """
            )


def _table_exists(conn: duckdb.DuckDBPyConnection, alias: str, table_name: str) -> bool:
    try:
        conn.execute(f"SELECT * FROM {alias}.{table_name} LIMIT 0")
        return True
    except duckdb.Error:
        return False
