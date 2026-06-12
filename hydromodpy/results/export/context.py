"""Shared context object that gathers data from the catalog for FAIR exports.

A :class:`FairExportContext` is a pure-data view of one simulation. It is
built once from the live :class:`Catalog` and then handed to the
specialised RO-Crate / STAC / PROV-O builders. Keeping a single
collector here means the rest of the exporters never touch DuckDB directly,
which also makes the layer matrix (``results -> core/schema/results/spatial``)
trivial to honour.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata as _importlib_metadata
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import WORKSPACE_TOML_FILENAME
from hydromodpy.core.workspace.workspace_toml import load_workspace_toml

logger = get_logger(__name__)

_DEFAULT_LICENSE = "https://creativecommons.org/licenses/by/4.0/"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hydromodpy_version() -> str:
    try:
        return _importlib_metadata.version("hydromodpy")
    except _importlib_metadata.PackageNotFoundError:
        return "unknown"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    text = str(value)
    return text or None


def _is_missing(val: Any) -> bool:
    """Return True when the value is empty, None, NaN or pandas NA."""
    if val is None:
        return True
    if isinstance(val, str):
        return val == ""
    try:
        import pandas as pd  # local import to avoid hard dependency in tests

        if pd.isna(val):  # type: ignore[arg-type]
            return True
    except (TypeError, ValueError):
        pass
    except ImportError:
        pass
    return False


def _coalesce(row: dict[str, Any], key: str) -> Any:
    if row is None:
        return None
    val = row.get(key)
    if _is_missing(val):
        return None
    return val


def _resolve_license(workspace_meta: dict[str, Any] | None) -> str:
    """Map workspace TOML license slug to a SPDX/CC URL."""
    if not workspace_meta:
        return _DEFAULT_LICENSE
    slug = str(workspace_meta.get("license", "")).strip().lower()
    if not slug:
        return _DEFAULT_LICENSE
    mapping = {
        "cc-by-4.0": "https://creativecommons.org/licenses/by/4.0/",
        "cc-by-sa-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
        "cc0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
        "mit": "https://spdx.org/licenses/MIT",
        "apache-2.0": "https://spdx.org/licenses/Apache-2.0",
        "etalab-2.0": "https://spdx.org/licenses/etalab-2.0",
        "proprietary": "https://spdx.org/licenses/LicenseRef-proprietary",
    }
    return mapping.get(slug, slug)


def _read_workspace_toml(workspace_path: Path) -> dict[str, Any]:
    """Return parsed ``workspace.toml`` content as a flat ``[workspace]`` dict.

    Validation runs through ``load_workspace_toml`` (Pydantic v2). When the
    file is missing or fails validation the function logs a warning and
    returns an empty mapping so FAIR exporters fall back to defaults.
    """
    toml_path = workspace_path / WORKSPACE_TOML_FILENAME
    if not toml_path.is_file():
        return {}
    try:
        validated = load_workspace_toml(workspace_path)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        logger.warning(
            "Invalid %s at %s; FAIR exporter falls back to defaults: %s",
            WORKSPACE_TOML_FILENAME,
            toml_path,
            exc,
        )
        return {}
    return validated.workspace.model_dump(mode="python")


@dataclass(frozen=True)
class AssetEntry:
    """One referenced artefact (Zarr, Parquet, COG, lockfile)."""

    key: str
    relative_path: str
    media_type: str
    roles: tuple[str, ...]
    sha256: str | None = None
    size_bytes: int | None = None
    description: str | None = None


@dataclass(frozen=True)
class InputEntry:
    """One workspace input file used by the simulation."""

    role: str
    category: str
    original_path: str
    sha256: str
    size_bytes: int
    source_type: str | None = None
    source_ref: str | None = None
    loader_name: str | None = None
    license: str | None = None
    data_provider: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class FairExportContext:
    """Read-only snapshot of every piece of metadata the exporters need."""

    sim_id: str
    sim_row: dict[str, Any]
    runs_env: dict[str, Any]
    workspace_meta: dict[str, Any]
    workspace_path: Path
    license_url: str
    creator_name: str | None
    creator_email: str | None
    assets: tuple[AssetEntry, ...]
    inputs: tuple[InputEntry, ...]
    lockfile_path: Path | None
    solver_binary_sha256: str | None
    solver_name: str | None
    solver_version: str | None
    hydromodpy_version: str
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    def asset_by_key(self, key: str) -> AssetEntry | None:
        for asset in self.assets:
            if asset.key == key:
                return asset
        return None

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        row = self.sim_row
        if not row:
            return None
        keys = ("bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax")
        if any(_is_missing(row.get(k)) for k in keys):
            return None
        return tuple(float(row[k]) for k in keys)  # type: ignore[return-value]

    @property
    def period_start(self) -> str | None:
        return _iso(_coalesce(self.sim_row, "period_start"))

    @property
    def period_end(self) -> str | None:
        return _iso(_coalesce(self.sim_row, "period_end"))


def _fetch_one(catalog: Any, sql: str, params: list[Any]) -> dict[str, Any] | None:
    df = catalog.backend.query(sql, params)
    if df.empty:
        return None
    return {str(k): df.iloc[0][k] for k in df.columns}


def _fetch_all(catalog: Any, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    df = catalog.backend.query(sql, params)
    if df.empty:
        return []
    return df.to_dict("records")


def _collect_assets(
    catalog: Any,
    workspace_path: Path,
    sim_row: dict[str, Any],
) -> list[AssetEntry]:
    assets: list[AssetEntry] = []
    zarr_rel = sim_row.get("zarr_path")
    if zarr_rel:
        zarr_path = workspace_path / str(zarr_rel)
        sha = _sha256_file(zarr_path) if zarr_path.is_file() else None
        size = zarr_path.stat().st_size if zarr_path.is_file() else None
        media = (
            "application/zip" if str(zarr_rel).endswith(".zarr.zip") else "application/x.zarr-store"
        )
        assets.append(
            AssetEntry(
                key="zarr",
                relative_path=str(zarr_rel).replace("\\", "/"),
                media_type=media,
                roles=("data", "fields"),
                sha256=sha,
                size_bytes=size,
                description="Zarr store with spatial fields, mesh and forcings.",
            )
        )

    parquet_root = getattr(catalog, "parquet_dir_for", None)
    if callable(parquet_root):
        try:
            pq_dir = Path(parquet_root(sim_row["sim_id"]))
        except Exception:
            pq_dir = None
        if pq_dir and pq_dir.is_dir():
            # ``pq_dir`` is the per-sim container; only single-file payloads
            # inside are valid asset entries.
            for pq in sorted(p for p in pq_dir.glob("*.parquet") if p.is_file()):
                rel = pq.relative_to(workspace_path) if workspace_path in pq.parents else pq.name
                assets.append(
                    AssetEntry(
                        key=f"parquet:{pq.stem}",
                        relative_path=str(rel).replace("\\", "/"),
                        media_type="application/vnd.apache.parquet",
                        roles=("data", "metadata"),
                        sha256=_sha256_file(pq),
                        size_bytes=pq.stat().st_size,
                        description=f"Per-simulation Parquet table: {pq.stem}.",
                    )
                )

    project = sim_row.get("project")
    if project:
        lock_path = workspace_path / "projects" / str(project) / "hydromodpy.lock"
        if lock_path.is_file():
            rel = lock_path.relative_to(workspace_path)
            assets.append(
                AssetEntry(
                    key="lockfile",
                    relative_path=str(rel).replace("\\", "/"),
                    media_type="application/toml",
                    roles=("metadata", "provenance"),
                    sha256=_sha256_file(lock_path),
                    size_bytes=lock_path.stat().st_size,
                    description="Reproducibility lockfile (versions + binaries).",
                )
            )
    return assets


def _collect_inputs(catalog: Any, sim_id: str) -> list[InputEntry]:
    rows = _fetch_all(
        catalog,
        "SELECT role, category, original_path, sha256, size_bytes "
        "FROM tracked_files WHERE sim_id = ? ORDER BY role, original_path",
        [sim_id],
    )
    prov = {
        (str(r["variable"]), str(r.get("source_ref", "") or "")): r
        for r in _fetch_all(
            catalog,
            "SELECT variable, source_ref, source_type, loader_name, license, "
            "data_provider, fetched_at FROM provenance WHERE sim_id = ?",
            [sim_id],
        )
    }
    inputs: list[InputEntry] = []
    for row in rows:
        role = str(row.get("role") or "")
        original = str(row.get("original_path") or "")
        match = None
        for (var, ref), prow in prov.items():
            if var == role and ref and original.endswith(ref):
                match = prow
                break
            if ref and original == ref:
                match = prow
                break
        inputs.append(
            InputEntry(
                role=role,
                category=str(row.get("category") or ""),
                original_path=original,
                sha256=str(row.get("sha256") or ""),
                size_bytes=int(row.get("size_bytes") or 0),
                source_type=str(match["source_type"])
                if match and match.get("source_type")
                else None,
                source_ref=str(match["source_ref"]) if match and match.get("source_ref") else None,
                loader_name=str(match["loader_name"])
                if match and match.get("loader_name")
                else None,
                license=str(match["license"]) if match and match.get("license") else None,
                data_provider=str(match["data_provider"])
                if match and match.get("data_provider")
                else None,
                fetched_at=_iso(match.get("fetched_at")) if match else None,
            )
        )
    return inputs


def build_context(catalog: Any, sim_id: str) -> FairExportContext:
    """Collect every catalog row and file the FAIR exporters need.

    The catalog object is duck-typed to keep the dependency direction
    aligned with the layer matrix (``results.export`` only touches
    ``results.catalog`` via attribute access, never via type imports).
    """
    sid = str(sim_id)
    sim_row = _fetch_one(
        catalog,
        "SELECT * FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
        [sid],
    )
    if sim_row is None:
        raise KeyError(f"Simulation '{sid}' not found in catalog")

    runs_env = (
        _fetch_one(
            catalog,
            "SELECT * FROM runs_environment WHERE CAST(sim_id AS VARCHAR) = ?",
            [sid],
        )
        or {}
    )
    workspace_path = Path(catalog.workspace_path)
    workspace_meta = _read_workspace_toml(workspace_path)
    license_url = _resolve_license(workspace_meta)

    members = (
        workspace_meta.get("team", {}).get("members")
        if isinstance(workspace_meta.get("team"), dict)
        else None
    )
    creator_name = (
        runs_env.get("user_name")
        or (members[0] if members else None)
        or workspace_meta.get("contact")
    )
    creator_email = sim_row.get("contact_email") or workspace_meta.get("contact")

    assets = _collect_assets(catalog, workspace_path, sim_row)
    inputs = _collect_inputs(catalog, sid)

    project = sim_row.get("project")
    lock_path: Path | None = None
    if project:
        candidate = workspace_path / "projects" / str(project) / "hydromodpy.lock"
        if candidate.is_file():
            lock_path = candidate

    return FairExportContext(
        sim_id=sid,
        sim_row=sim_row,
        runs_env=runs_env,
        workspace_meta=workspace_meta,
        workspace_path=workspace_path,
        license_url=license_url,
        creator_name=str(creator_name) if creator_name else None,
        creator_email=str(creator_email) if creator_email else None,
        assets=tuple(assets),
        inputs=tuple(inputs),
        lockfile_path=lock_path,
        solver_binary_sha256=(
            str(runs_env.get("solver_binary_sha256"))
            if runs_env.get("solver_binary_sha256")
            else None
        ),
        solver_name=str(runs_env.get("solver_name")) if runs_env.get("solver_name") else None,
        solver_version=(
            str(runs_env.get("solver_version_text"))
            if runs_env.get("solver_version_text")
            else None
        ),
        hydromodpy_version=str(runs_env.get("hydromodpy_version") or _hydromodpy_version()),
    )


def to_json(payload: Any, path: Path) -> Path:
    """Write *payload* deterministically as UTF-8 JSON and return *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "AssetEntry",
    "FairExportContext",
    "InputEntry",
    "build_context",
    "to_json",
]
