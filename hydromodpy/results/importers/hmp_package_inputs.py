"""Dematerialise the ``inputs/`` folder of a .hmp archive into a workspace."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class InputCollisionError(RuntimeError):
    """Raised when an incoming input has the same path but a different SHA."""

    def __init__(self, target: Path, existing_sha: str, incoming_sha: str) -> None:
        self.target = target
        self.existing_sha = existing_sha
        self.incoming_sha = incoming_sha
        super().__init__(
            f"File collision at {target}\n"
            f"  existing SHA: {existing_sha}\n"
            f"  incoming SHA: {incoming_sha}\n"
            "Same name, different content. Resolve manually before import."
        )


@dataclass(frozen=True)
class _Plan:
    entry: dict[str, Any]
    archive_source: Path
    target: Path
    action: str  # "copy", "reuse", "skip"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_directory(root: Path) -> str:
    """Deterministic SHA-256 over a directory tree (for dedup checks)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/").encode("utf-8")
        h.update(rel)
        h.update(b"\0")
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    return h.hexdigest()


def _derive_basename(entry: dict, archive_source: Path) -> str:
    """Return the filename (or directory name) to materialise under data/role/."""
    original = entry.get("original_path", "")
    if original:
        original_name = Path(str(original)).name
        if original_name:
            return original_name
    return archive_source.name


def plan_dematerialise_inputs(
    pkg: Path, workspace_root: Path, inputs: list[dict],
) -> list[_Plan]:
    """Compute per-entry copy/reuse/abort decisions without touching disk."""
    data_dir = workspace_root / "data"
    plans: list[_Plan] = []
    for entry in inputs:
        role = str(entry["role"])
        archive_rel = str(entry["archive_path"])
        archive_source = pkg / archive_rel
        if not archive_source.exists():
            raise FileNotFoundError(
                f"Missing bundled input in archive: {archive_rel}"
            )

        target_basename = _derive_basename(entry, archive_source)
        target = data_dir / role / target_basename

        action = "copy"
        if target.exists():
            incoming_sha = str(entry["sha256"])
            if target.is_dir() and archive_source.is_dir():
                existing_sha = _sha256_directory(target)
                expected_sha = _sha256_directory(archive_source)
                if existing_sha == expected_sha:
                    action = "reuse"
                else:
                    raise InputCollisionError(target, existing_sha, expected_sha)
            elif target.is_file() and archive_source.is_file():
                if archive_source.suffix == ".zip":
                    # Shapefile zip: cannot hash the extracted result cheaply,
                    # so compare archive sha of the source with existing
                    # serialized payload. In practice shapefile collisions
                    # are rare; we warn and abort if target is not a zip too.
                    existing_sha = _sha256_file(target)
                    if existing_sha == incoming_sha:
                        action = "reuse"
                    else:
                        raise InputCollisionError(target, existing_sha, incoming_sha)
                else:
                    existing_sha = _sha256_file(target)
                    if existing_sha == incoming_sha:
                        action = "reuse"
                    else:
                        raise InputCollisionError(target, existing_sha, incoming_sha)
            else:
                raise InputCollisionError(
                    target, "unknown", str(entry["sha256"])
                )

        plans.append(_Plan(entry=entry, archive_source=archive_source,
                           target=target, action=action))
    return plans


def _extract_shapefile_zip(zip_path: Path, dst_base: Path) -> Path:
    """Extract a .shp.zip next to the target .shp path.

    Returns the resolved .shp file path.
    """
    import zipfile

    dst_base.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path), "r") as zf:
        names = zf.namelist()
        zf.extractall(str(dst_base.parent))

    shp = next((n for n in names if n.lower().endswith(".shp")), None)
    if shp is None:
        raise RuntimeError(
            f"Archive {zip_path} does not contain a .shp component"
        )
    return (dst_base.parent / shp).resolve()


def dematerialise_inputs(
    pkg: Path, workspace_root: Path, manifest: dict,
    *, dry_run: bool = False,
) -> dict[str, str]:
    """Materialise inputs and return a mapping ``original_path -> new_path``.

    The mapping is what the import flow uses to rewrite the config TOML
    (or any stored config snapshot). When ``dry_run`` is true, no files
    are written; the planning output is still returned so callers can
    preview the resulting layout.
    """
    inputs = list(manifest.get("inputs", []))
    if not inputs:
        return {}

    plans = plan_dematerialise_inputs(pkg, workspace_root, inputs)

    rewrites: dict[str, str] = {}
    for plan in plans:
        entry = plan.entry
        archive_source = plan.archive_source
        target = plan.target
        original_path = str(entry.get("original_path", ""))

        if plan.action == "reuse":
            logger.info("Reusing existing %s (sha match)", target)
            rewrites[original_path] = str(target.resolve())
            continue

        if dry_run:
            rewrites[original_path] = str(target.resolve())
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if archive_source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(archive_source, target)
            rewrites[original_path] = str(target.resolve())
        elif archive_source.suffix == ".zip" and str(entry["role"]).endswith("polygon"):
            shp_target = _extract_shapefile_zip(archive_source, target)
            rewrites[original_path] = str(shp_target)
        elif archive_source.suffix == ".zip":
            shutil.copy2(archive_source, target)
            rewrites[original_path] = str(target.resolve())
        else:
            shutil.copy2(archive_source, target)
            rewrites[original_path] = str(target.resolve())

    return rewrites
