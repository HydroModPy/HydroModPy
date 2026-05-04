"""Legacy storage-name normalization helpers.

Older result catalogs used the raw ``sim_id`` as the on-disk basename and left
``simulations.storage_basename`` empty. The current layout uses
``<project>__<name>__<shortuuid>``. This module plans and applies that
filesystem/catalog migration without changing simulation identities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from hydromodpy.results.catalog.storage_paths import build_storage_basename
from hydromodpy.results.catalog_schema import ensure_parquet_views
from hydromodpy.results.storage_contract import (
    PARQUET_DIR_SUFFIX,
    SIMULATIONS_DIRNAME,
    ZARR_SUFFIX,
    ZARR_ZIP_SUFFIX,
)


@dataclass(frozen=True, slots=True)
class StorageNormalizationAction:
    """One planned legacy-storage normalization action."""

    sim_id: str
    project: str | None
    name: str | None
    old_basename: str
    new_basename: str
    status: str
    reason: str | None = None
    zarr_source: str | None = None
    zarr_target: str | None = None
    parquet_source: str | None = None
    parquet_target: str | None = None
    zarr_catalog_path: str | None = None

    @property
    def ready(self) -> bool:
        """Whether this action can be applied."""
        return self.status == "ready"

    def to_dict(self) -> dict[str, str | bool | None]:
        """Return a JSON-friendly representation."""
        return {**asdict(self), "ready": self.ready}


def plan_storage_name_normalization(conn, workspace: Path, simulations_dir: Path):
    """Plan legacy ``storage_basename`` normalization for one catalog."""
    rows = conn.execute(
        "SELECT CAST(sim_id AS VARCHAR), project, name, zarr_path "
        "FROM simulations "
        "WHERE storage_basename IS NULL "
        "ORDER BY created_at, sim_id"
    ).fetchall()
    reserved = {
        str(row[0])
        for row in conn.execute(
            "SELECT storage_basename FROM simulations WHERE storage_basename IS NOT NULL"
        ).fetchall()
    }
    return tuple(
        _plan_row(
            workspace=workspace,
            simulations_dir=simulations_dir,
            reserved_basenames=reserved,
            sim_id=str(sim_id),
            project=str(project) if project is not None else None,
            name=str(name) if name is not None else None,
            zarr_path=str(zarr_path) if zarr_path else None,
        )
        for sim_id, project, name, zarr_path in rows
    )


def apply_storage_name_normalization(
    conn,
    workspace: Path,
    simulations_dir: Path,
    actions: tuple[StorageNormalizationAction, ...],
    *,
    close_open_zarr_handles,
    cache_basename,
) -> tuple[StorageNormalizationAction, ...]:
    """Apply ready legacy-storage normalization actions."""
    applied: list[StorageNormalizationAction] = []
    close_open_zarr_handles()
    for action in actions:
        if not action.ready:
            applied.append(action)
            continue
        moved: list[tuple[Path, Path]] = []
        try:
            for source_raw, target_raw in (
                (action.zarr_source, action.zarr_target),
                (action.parquet_source, action.parquet_target),
            ):
                if not source_raw or not target_raw:
                    continue
                source = Path(source_raw)
                target = Path(target_raw)
                if not source.exists() or source.resolve() == target.resolve():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
                moved.append((source, target))

            conn.execute("BEGIN TRANSACTION")
            try:
                if action.zarr_catalog_path is None:
                    conn.execute(
                        "UPDATE simulations SET storage_basename = ? WHERE sim_id = ?",
                        [action.new_basename, action.sim_id],
                    )
                else:
                    conn.execute(
                        "UPDATE simulations "
                        "SET storage_basename = ?, zarr_path = ? "
                        "WHERE sim_id = ?",
                        [action.new_basename, action.zarr_catalog_path, action.sim_id],
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except Exception:
            for source, target in reversed(moved):
                if target.exists() and not source.exists():
                    target.rename(source)
            raise

        cache_basename(action.sim_id, action.new_basename)
        applied.append(action)

    if any(action.ready and action.parquet_target for action in actions):
        ensure_parquet_views(conn, simulations_dir)
    return tuple(applied)


def _plan_row(
    *,
    workspace: Path,
    simulations_dir: Path,
    reserved_basenames: set[str],
    sim_id: str,
    project: str | None,
    name: str | None,
    zarr_path: str | None,
) -> StorageNormalizationAction:
    old_basename = sim_id
    new_basename = build_storage_basename(project, name, sim_id)
    reason: str | None = None
    zarr_source, zarr_target, zarr_catalog_path, zarr_reason = _plan_zarr(
        workspace=workspace,
        simulations_dir=simulations_dir,
        old_basename=old_basename,
        new_basename=new_basename,
        zarr_path=zarr_path,
    )
    parquet_source, parquet_target, parquet_reason = _plan_parquet(
        simulations_dir=simulations_dir,
        old_basename=old_basename,
        new_basename=new_basename,
    )

    if new_basename in reserved_basenames:
        reason = f"target basename already belongs to another simulation: {new_basename}"
    elif zarr_reason:
        reason = zarr_reason
    elif parquet_reason:
        reason = parquet_reason

    return StorageNormalizationAction(
        sim_id=sim_id,
        project=project,
        name=name,
        old_basename=old_basename,
        new_basename=new_basename,
        status="blocked" if reason else "ready",
        reason=reason,
        zarr_source=str(zarr_source) if zarr_source else None,
        zarr_target=str(zarr_target) if zarr_target else None,
        parquet_source=str(parquet_source) if parquet_source else None,
        parquet_target=str(parquet_target) if parquet_target else None,
        zarr_catalog_path=zarr_catalog_path,
    )


def _plan_zarr(
    *,
    workspace: Path,
    simulations_dir: Path,
    old_basename: str,
    new_basename: str,
    zarr_path: str | None,
) -> tuple[Path | None, Path | None, str | None, str | None]:
    source = _existing_zarr_source(workspace, simulations_dir, old_basename, zarr_path)
    source_suffix = _zarr_suffix(source) if source else _zarr_suffix_from_catalog(zarr_path)

    target = None
    catalog_path = None
    reason = None
    if source_suffix is not None:
        target = simulations_dir / f"{new_basename}{source_suffix}"
        catalog_path = f"{SIMULATIONS_DIRNAME}/{target.name}"
        if source is not None and target.exists() and source.resolve() != target.resolve():
            reason = f"target Zarr artefact already exists: {target}"
    else:
        target = _existing_new_zarr_target(simulations_dir, new_basename)
        if target is not None:
            catalog_path = f"{SIMULATIONS_DIRNAME}/{target.name}"
    return source, target, catalog_path, reason


def _existing_zarr_source(
    workspace: Path,
    simulations_dir: Path,
    old_basename: str,
    zarr_path: str | None,
) -> Path | None:
    candidates: list[Path] = []
    if zarr_path:
        declared = Path(zarr_path)
        candidates.append(declared if declared.is_absolute() else workspace / declared)
    candidates.extend(
        [
            simulations_dir / f"{old_basename}{ZARR_ZIP_SUFFIX}",
            simulations_dir / f"{old_basename}{ZARR_SUFFIX}",
        ]
    )
    for candidate in candidates:
        if candidate.exists() and storage_path_basename(candidate) == old_basename:
            return candidate
    return None


def _existing_new_zarr_target(simulations_dir: Path, new_basename: str) -> Path | None:
    for suffix in (ZARR_ZIP_SUFFIX, ZARR_SUFFIX):
        candidate = simulations_dir / f"{new_basename}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _zarr_suffix(path: Path | None) -> str | None:
    if path is None:
        return None
    name = path.name
    if name.endswith(ZARR_ZIP_SUFFIX):
        return ZARR_ZIP_SUFFIX
    if name.endswith(ZARR_SUFFIX):
        return ZARR_SUFFIX
    return None


def _zarr_suffix_from_catalog(zarr_path: str | None) -> str | None:
    if not zarr_path:
        return None
    name = Path(zarr_path).name
    if name.endswith(ZARR_ZIP_SUFFIX):
        return ZARR_ZIP_SUFFIX
    if name.endswith(ZARR_SUFFIX):
        return ZARR_SUFFIX
    return None


def _plan_parquet(
    *,
    simulations_dir: Path,
    old_basename: str,
    new_basename: str,
) -> tuple[Path | None, Path | None, str | None]:
    source = simulations_dir / f"{old_basename}{PARQUET_DIR_SUFFIX}"
    target = simulations_dir / f"{new_basename}{PARQUET_DIR_SUFFIX}"
    source_exists = source.is_dir()
    target_exists = target.is_dir()
    if source_exists and target_exists and source.resolve() != target.resolve():
        return source, target, f"target Parquet directory already exists: {target}"
    if source_exists:
        return source, target, None
    if target_exists:
        return None, target, None
    return None, None, None


def storage_path_basename(path: Path) -> str:
    """Return the basename for known simulation artefact paths."""
    name = path.name
    for suffix in (ZARR_ZIP_SUFFIX, ZARR_SUFFIX, PARQUET_DIR_SUFFIX):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


__all__ = [
    "StorageNormalizationAction",
    "apply_storage_name_normalization",
    "plan_storage_name_normalization",
]
