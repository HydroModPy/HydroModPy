"""Backend logic for ``hmp dev manage``: workspace inspection and cleanup."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd

from hydromodpy.cli._workers.catalog import delete_simulation_artifacts
from hydromodpy.core.state.paths import CATALOG_FILENAME
from hydromodpy.results.storage_contract import SIMULATIONS_DIRNAME
from hydromodpy.results.storage_diagnostics import (
    diagnose_result_storage,
    storage_artefact_basename,
    storage_artefact_kind,
)


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        if path.is_file():
            return int(path.stat().st_size)
    except OSError:
        return 0

    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += int(child.stat().st_size)
            except OSError:
                continue
    except OSError:
        return total
    return total


def _artefact_kind(path: Path) -> str | None:
    return storage_artefact_kind(path)


def _artefact_basename(path: Path) -> str:
    return storage_artefact_basename(path)


def _workspace_label(path: Path, scan_root: Path) -> str:
    try:
        rel = path.resolve().relative_to(scan_root.resolve())
        if str(rel) == ".":
            return path.resolve().name or str(path.resolve())
        return str(rel)
    except ValueError:
        return str(path.resolve())


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path | UUID):
        return str(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if hasattr(value, "item"):
        try:
            scalar = value.item()
        except Exception:
            scalar = None
        if scalar is not None and scalar is not value:
            return _json_value(scalar)
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


class _WorkspaceManagerBackend:
    """Read and mutate one workspace in a browser-friendly shape."""

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        scan_root: Path | None = None,
    ) -> None:
        if workspace_root is not None:
            root = workspace_root.resolve()
            self.scan_root = root
            roots = [root]
        else:
            if scan_root is None:
                raise ValueError("scan_root is required when workspace_root is omitted")
            self.scan_root = scan_root.resolve()
            if not self.scan_root.is_dir():
                raise FileNotFoundError(f"Scan root does not exist: {self.scan_root}")
            roots = self._discover_workspaces(self.scan_root)
            if not roots:
                raise FileNotFoundError(
                    f"No HydroModPy workspace found under {self.scan_root} "
                    f"(missing {CATALOG_FILENAME} files)."
                )

        ordered = self._order_workspaces(roots)
        self.workspace_roots = {str(path): path for path in ordered}
        self.default_workspace = str(ordered[0])

    def list_workspaces(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for path in self.workspace_roots.values():
            rows.append(
                {
                    "id": str(path),
                    "path": str(path),
                    "label": _workspace_label(path, self.scan_root),
                    "catalog_exists": (path / CATALOG_FILENAME).is_file(),
                    "cache_exists": (path / "data" / "cache.duckdb").is_file(),
                }
            )
        return {
            "scan_root": str(self.scan_root),
            "default_workspace": self.default_workspace,
            "workspaces": rows,
        }

    def summary(self, workspace_ref: str | None = None) -> dict[str, Any]:
        workspace_root = self._resolve_workspace(workspace_ref)
        simulations = self.list_simulations(workspace_ref)["rows"]
        orphans = self.list_orphans(workspace_ref)["rows"]
        diagnostics = self.result_diagnostics(workspace_ref)["rows"]
        catalog_path = workspace_root / CATALOG_FILENAME
        cache_path = workspace_root / "data" / "cache.duckdb"
        return {
            "workspace": str(workspace_root),
            "workspace_label": _workspace_label(workspace_root, self.scan_root),
            "scan_root": str(self.scan_root),
            "workspace_count": len(self.workspace_roots),
            "catalog_bytes": _path_size(catalog_path),
            "cache_bytes": _path_size(cache_path),
            "simulation_count": len(simulations),
            "simulation_bytes": sum(int(row["total_bytes"]) for row in simulations),
            "orphan_bytes": sum(int(row["size_bytes"]) for row in orphans),
            "diagnostic_warning_count": sum(1 for row in diagnostics if row.get("status") != "OK"),
        }

    def result_diagnostics(self, workspace_ref: str | None = None) -> dict[str, Any]:
        workspace_root = self._resolve_workspace(workspace_ref)
        rows: list[dict[str, Any]] = []
        for diagnostic in diagnose_result_storage(workspace_root):
            record = dict(diagnostic.to_check())
            paths = [str(path) for path in record.get("paths", ()) or ()]
            record["paths"] = paths
            record["cleanup_count"] = len(paths)
            record["cleanup_bytes"] = sum(_path_size(Path(path)) for path in paths)
            rows.append(record)
        return {"rows": rows}

    def list_simulations(self, workspace_ref: str | None = None) -> dict[str, Any]:
        from hydromodpy.results.catalog import SimulationCatalog

        workspace_root = self._resolve_workspace(workspace_ref)
        catalog_path = workspace_root / CATALOG_FILENAME
        if not catalog_path.exists():
            return {"rows": []}

        rows: list[dict[str, Any]] = []
        with SimulationCatalog(workspace_root) as catalog:
            df = catalog.list_simulations(order_by="created_at DESC")
            for _, raw in df.iterrows():
                record = {str(key): _json_value(value) for key, value in raw.items()}
                sim_id = str(record.get("sim_id", ""))
                zarr_path = catalog.zarr_path_for(sim_id)
                parquet_dir = catalog.parquet_dir_for(sim_id)
                zarr_bytes = _path_size(zarr_path)
                parquet_bytes = _path_size(parquet_dir)
                record.update(
                    {
                        "sim_id": sim_id,
                        "zarr_path": str(zarr_path),
                        "zarr_exists": zarr_path.exists(),
                        "zarr_bytes": zarr_bytes,
                        "parquet_dir": str(parquet_dir),
                        "parquet_exists": parquet_dir.exists(),
                        "parquet_bytes": parquet_bytes,
                        "total_bytes": zarr_bytes + parquet_bytes,
                    }
                )
                rows.append(record)
        return {"rows": rows}

    def delete_simulations(
        self,
        workspace_ref: str | None,
        sim_ids: list[str],
    ) -> dict[str, Any]:
        from hydromodpy.results.catalog import SimulationCatalog

        workspace_root = self._resolve_workspace(workspace_ref)
        deleted: list[dict[str, Any]] = []
        with SimulationCatalog(workspace_root) as catalog:
            for sim_id in sim_ids:
                run = catalog[sim_id]
                result = delete_simulation_artifacts(catalog, sim_id)
                deleted.append(
                    {
                        "sim_id": sim_id,
                        "name": run.name or sim_id,
                        "freed_bytes": int(result["freed_bytes"]),
                        "removed_paths": list(result["removed_paths"]),
                    }
                )
        return {
            "deleted": deleted,
            "freed_bytes": sum(int(item["freed_bytes"]) for item in deleted),
        }

    def list_orphans(self, workspace_ref: str | None = None) -> dict[str, Any]:
        workspace_root = self._resolve_workspace(workspace_ref)
        catalog_path = workspace_root / CATALOG_FILENAME
        simulations_dir = workspace_root / SIMULATIONS_DIRNAME
        registered: set[str] = set()
        if catalog_path.exists():
            from hydromodpy.results.catalog import SimulationCatalog

            with SimulationCatalog(workspace_root) as catalog:
                rows = catalog.connection.execute(
                    "SELECT CAST(sim_id AS VARCHAR) AS sim_id, storage_basename FROM simulations"
                ).fetchall()
                registered = {str(storage_basename) for _, storage_basename in rows}

        artefacts: list[dict[str, Any]] = []
        if not simulations_dir.is_dir():
            return {"rows": artefacts}

        for path in sorted(simulations_dir.iterdir()):
            if not (path.is_dir() or path.is_file()):
                continue
            kind = _artefact_kind(path)
            if kind is None:
                continue
            basename = _artefact_basename(path)
            if basename in registered:
                continue
            artefacts.append(
                {
                    "path": str(path),
                    "basename": basename,
                    "kind": kind,
                    "size_bytes": _path_size(path),
                }
            )
        return {"rows": artefacts}

    def delete_orphans(
        self,
        workspace_ref: str | None,
        paths: list[str],
    ) -> dict[str, Any]:
        workspace_root = self._resolve_workspace(workspace_ref)
        simulations_dir = workspace_root / SIMULATIONS_DIRNAME
        deleted: list[dict[str, Any]] = []
        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            if not _is_relative_to(path, simulations_dir):
                raise ValueError(f"Refusing to delete outside simulations/: {path}")
            if not path.exists():
                continue
            freed_bytes = _path_size(path)
            if path.is_dir():
                import shutil

                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            deleted.append({"path": str(path), "freed_bytes": freed_bytes})
        return {
            "deleted": deleted,
            "freed_bytes": sum(int(item["freed_bytes"]) for item in deleted),
        }

    def list_tables(self, workspace_ref: str | None, database: str) -> dict[str, Any]:
        db_path = self._db_path(self._resolve_workspace(workspace_ref), database)
        if not db_path.exists():
            return {"database": database, "tables": []}

        import duckdb

        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            rows = conn.execute(
                "SELECT table_name, table_type FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_type, table_name"
            ).fetchall()
        finally:
            conn.close()
        return {
            "database": database,
            "tables": [{"name": str(name), "type": str(table_type)} for name, table_type in rows],
        }

    def preview_table(
        self,
        workspace_ref: str | None,
        database: str,
        table: str,
        limit: int,
    ) -> dict[str, Any]:
        db_path = self._db_path(self._resolve_workspace(workspace_ref), database)
        if not db_path.exists():
            raise FileNotFoundError(f"No {database} database at {db_path}")

        limit = max(10, min(int(limit), 500))
        allowed = {entry["name"] for entry in self.list_tables(workspace_ref, database)["tables"]}
        if table not in allowed:
            raise ValueError(f"Unknown table '{table}' in {database}")

        import duckdb

        from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend

        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            backend = DuckDBBackend.from_connection(conn)
            df = backend.query(
                f'SELECT * FROM "{table.replace(chr(34), chr(34) * 2)}" LIMIT {limit}'
            )
        finally:
            conn.close()
        rows = [
            {str(column): _json_value(value) for column, value in row.items()}
            for row in df.to_dict(orient="records")
        ]
        return {
            "database": database,
            "table": table,
            "columns": list(df.columns),
            "rows": rows,
            "row_count": len(rows),
        }

    def _resolve_workspace(self, workspace_ref: str | None) -> Path:
        key = str(workspace_ref or self.default_workspace)
        try:
            return self.workspace_roots[key]
        except KeyError as exc:
            raise ValueError(f"Unknown workspace '{key}'") from exc

    def _db_path(self, workspace_root: Path, database: str) -> Path:
        if database == "catalog":
            return workspace_root / CATALOG_FILENAME
        if database == "cache":
            return workspace_root / "data" / "cache.duckdb"
        raise ValueError(f"Unsupported database '{database}'")

    @staticmethod
    def _discover_workspaces(scan_root: Path) -> list[Path]:
        roots = {
            path.parent.resolve() for path in scan_root.rglob(CATALOG_FILENAME) if path.is_file()
        }
        return sorted(roots)

    def _order_workspaces(self, roots: list[Path]) -> list[Path]:
        examples_root = (self.scan_root / "examples").resolve()

        def sort_key(path: Path) -> tuple[int, int, str]:
            path_str = str(path).lower()
            is_examples = 0 if path == examples_root else 1
            is_tmp = 1 if "\\tmp\\" in path_str or path_str.endswith("\\tmp") else 0
            return (is_examples, is_tmp, _workspace_label(path, self.scan_root).lower())

        return sorted(roots, key=sort_key)
