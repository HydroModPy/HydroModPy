"""Fixture helpers for the migration round-trip tests.

The bundled ``fixtures/`` directory carries deterministic recipes (one
``<slug>.recipe.json`` per fixture) describing how to materialise a v1
DuckDB catalog. Storing recipes instead of binary blobs keeps the
fixtures portable across DuckDB releases and reviewable in git.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.paths import RUNS_DIRNAME
from hydromodpy.results.catalog.migrations import MIGRATIONS_DIR
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_V1_FILENAME = "0001_initial.sql"


def _apply_v1_schema(db_path: Path) -> None:
    """Apply only migration ``0001`` to ``db_path`` so it stays at version 1."""
    sql = (Path(MIGRATIONS_DIR) / _V1_FILENAME).read_text(encoding="utf-8")
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER NOT NULL,
                component   VARCHAR NOT NULL,
                slug        VARCHAR NOT NULL,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                checksum    VARCHAR NOT NULL,
                PRIMARY KEY (component, version)
            );
            CREATE TABLE IF NOT EXISTS _schema_version (
                component   VARCHAR PRIMARY KEY,
                version     INTEGER NOT NULL,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(sql)
            import hashlib

            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO schema_migrations (version, component, slug, checksum) "
                "VALUES (1, 'catalog', 'initial', ?)",
                [checksum],
            )
            conn.execute("INSERT INTO _schema_version (component, version) VALUES ('catalog', 1)")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _seed_fixture(db_path: Path, recipe: dict) -> None:
    """Insert recipe-provided rows into a freshly v1-bootstrapped database."""
    seed_simulations = recipe.get("simulations", [])
    if not seed_simulations:
        return
    conn = duckdb.connect(str(db_path))
    try:
        for entry in seed_simulations:
            sid = entry["sim_id"]
            run_name = entry.get("name") or sid.replace("-", "")[:12]
            storage_basename = entry.get("storage_basename", run_name)
            zarr_path = entry.get(
                "zarr_path", f"{RUNS_DIRNAME}/{storage_basename}/{FIELDS_STORE_NAME}"
            )
            conn.execute(
                """INSERT INTO simulations
                   (sim_id, name, project,
                    solver_id, status_id, zarr_path, storage_basename)
                   VALUES (?, ?, ?,
                           (SELECT id FROM solvers WHERE code = ?),
                           (SELECT id FROM statuses WHERE code = ?),
                           ?, ?)""",
                [
                    sid,
                    entry.get("name"),
                    entry.get("project", "lab"),
                    entry.get("solver", "modflow6"),
                    entry.get("status", "completed"),
                    zarr_path,
                    storage_basename,
                ],
            )
    finally:
        conn.close()


@pytest.fixture
def v1_fixture_path(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """Materialise a v1 DuckDB catalog from a fixture recipe.

    Parametrise the test with the recipe stem (without the ``.recipe.json``
    suffix) and call ``request.param`` to pick it up.
    """
    stem = request.param
    recipe_file = FIXTURES_DIR / f"{stem}.recipe.json"
    recipe = json.loads(recipe_file.read_text(encoding="utf-8"))
    db_path = tmp_path / f"{stem}.duckdb"
    _apply_v1_schema(db_path)
    _seed_fixture(db_path, recipe)
    return db_path


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


def discover_fixture_stems() -> list[str]:
    return sorted(p.stem.replace(".recipe", "") for p in FIXTURES_DIR.glob("*.recipe.json"))


def materialise_v1_db(stem: str, dest: Path) -> Path:
    """Public helper to materialise a v1 catalog at ``dest`` from ``stem``."""
    recipe_file = FIXTURES_DIR / f"{stem}.recipe.json"
    recipe = json.loads(recipe_file.read_text(encoding="utf-8"))
    if dest.exists():
        dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    _apply_v1_schema(dest)
    _seed_fixture(dest, recipe)
    return dest


def copy_fixture(stem: str, dest_dir: Path) -> Path:
    """Materialise a fresh v1 fixture into ``dest_dir`` and return the path."""
    dest = dest_dir / f"{stem}.duckdb"
    return materialise_v1_db(stem, dest)


__all__ = [
    "FIXTURES_DIR",
    "copy_fixture",
    "discover_fixture_stems",
    "fixtures_dir",
    "materialise_v1_db",
    "v1_fixture_path",
]
