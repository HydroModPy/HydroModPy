"""Portable ``.hmp`` package export / import with geographic materialization.

The workspace keeps raster geographic artefacts (DEM, geology) in a shared,
content-addressable cache (see :mod:`hydromodpy.results.geographic_cache`).
Individual simulation Zarr stores only hold a fingerprint string, which keeps
calibration runs that share a catchment from duplicating GB of rasters.

When a simulation is exported for sharing, however, the archive must be
self-contained. This module handles the round-trip:

* **export** — resolve the simulation's ``geographic_fingerprint``, copy the
  matching ``workspace/geographic/<fp>/`` directory into the archive under
  ``geographic/``.
* **import** — de-materialise the ``geographic/`` directory back into the
  destination workspace cache so subsequent imports of sibling simulations
  (same fingerprint) reuse it without duplication.

The archive layout is the pragmatic form used by the current release; it will
evolve into the full ``tar.zst`` manifest described in
``architecture_cible/04_storage_ideal.md`` in a later phase.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from hydromodpy.results.geographic_cache import (
    CACHE_DIRNAME,
    MANIFEST_FILENAME,
    GeographicCache,
)

logger = logging.getLogger(__name__)

GEOGRAPHIC_SUBDIR = "geographic"


def materialize_geographic_on_export(
    workspace_path: Path | str,
    fingerprint: str | None,
    package_dir: Path | str,
) -> Path | None:
    """Copy cached geographic payload into ``package_dir/geographic/``.

    Returns the populated path (or ``None`` when the simulation carries no
    fingerprint). Missing cache entries are logged and skipped so an export
    never fails hard on a stale or partial cache — the ``.hmp`` may then be
    ``metadata-only``.
    """
    if not fingerprint:
        return None

    cache = GeographicCache(workspace_path)
    if not cache.is_cached(fingerprint):
        logger.warning(
            "Geographic fingerprint %s not found in cache %s; export will "
            "ship without geographic payload",
            fingerprint, cache.root,
        )
        return None

    pkg = Path(package_dir)
    dst = pkg / GEOGRAPHIC_SUBDIR
    pkg.mkdir(parents=True, exist_ok=True)
    src = cache.load(fingerprint)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    # Side-car manifest at archive root for inspection tools.
    manifest = {
        "fingerprint": fingerprint,
        "source_cache": str(cache.root),
    }
    (pkg / "geographic_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
    )
    return dst


def dematerialize_geographic_on_import(
    package_dir: Path | str,
    workspace_path: Path | str,
    fingerprint: str | None = None,
    *,
    overwrite: bool = False,
) -> str | None:
    """Move the archive's ``geographic/`` payload into the destination cache.

    If ``fingerprint`` is not supplied, it is read from
    ``geographic/<MANIFEST_FILENAME>`` (the side-car written by the cache).
    Returns the fingerprint placed in the cache, or ``None`` when the
    archive has no geographic payload.
    """
    pkg = Path(package_dir)
    src = pkg / GEOGRAPHIC_SUBDIR
    if not src.is_dir():
        return None

    if fingerprint is None:
        manifest_path = src / MANIFEST_FILENAME
        if manifest_path.is_file():
            try:
                fingerprint = str(
                    json.loads(manifest_path.read_text()).get("fingerprint")
                )
            except (json.JSONDecodeError, OSError):
                fingerprint = None
        if not fingerprint:
            # Fallback to the archive-level manifest if the cache manifest
            # was stripped.
            top_manifest = pkg / "geographic_manifest.json"
            if top_manifest.is_file():
                try:
                    fingerprint = str(
                        json.loads(top_manifest.read_text()).get("fingerprint")
                    )
                except (json.JSONDecodeError, OSError):
                    fingerprint = None
    if not fingerprint:
        logger.warning(
            "Skipping geographic de-materialisation: no fingerprint in %s",
            pkg,
        )
        return None

    cache = GeographicCache(workspace_path)
    cache.save(
        fingerprint, src, manifest=_read_manifest(src), overwrite=overwrite,
    )
    return fingerprint


def _read_manifest(src: Path) -> dict[str, Any]:
    manifest_path = src / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


__all__ = [
    "CACHE_DIRNAME",
    "GEOGRAPHIC_SUBDIR",
    "materialize_geographic_on_export",
    "dematerialize_geographic_on_import",
]
