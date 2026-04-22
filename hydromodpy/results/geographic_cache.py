"""Workspace-level content-addressable geographic cache.

A catchment may be re-used across hundreds of simulations (e.g. calibration
runs sweeping hydraulic parameters on a fixed domain). The geographic
artefacts — DEM raster, geology raster, watershed polygon, river network —
are identical across all those runs and do not need to be duplicated inside
each ``simulations/<uuid>.zarr``.

This module provides :class:`GeographicCache`, a deterministic, read-through
cache keyed by a SHA-256 fingerprint computed from the resolved spatial
inputs:

* DEM path + file SHA-256 + bounding box + resolution;
* geology path + file SHA-256;
* CRS, bbox, delineation options.

Simulations store only the fingerprint string (via
``simulations.geographic_fingerprint``); the actual arrays live once per
unique input set under ``workspace/geographic/<fingerprint>/``.

Portable packages (.hmp) rematerialise the cache directory on export and
redeposit it on import, keeping the archive self-contained without giving up
the deduplication benefit inside the workspace.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Sub-directory under ``workspace/`` that hosts the shared cache.
CACHE_DIRNAME = "geographic"

#: Attribute key written on each ``<fingerprint>/`` directory to tie a
#: fingerprint back to its input descriptor for debugging and audit.
MANIFEST_FILENAME = "fingerprint.json"


@dataclass(frozen=True)
class GeographicInputs:
    """Normalized, fingerprintable description of spatial inputs.

    Any field not provided is excluded from the fingerprint. This keeps the
    hash stable as new optional fields are added later.
    """

    dem_path: str | None = None
    dem_sha256: str | None = None
    geology_path: str | None = None
    geology_sha256: str | None = None
    crs_wkt: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    resolution_m: float | None = None
    extra: Mapping[str, Any] | None = None

    def as_canonical_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.dem_path:
            d["dem_path"] = str(self.dem_path)
        if self.dem_sha256:
            d["dem_sha256"] = self.dem_sha256
        if self.geology_path:
            d["geology_path"] = str(self.geology_path)
        if self.geology_sha256:
            d["geology_sha256"] = self.geology_sha256
        if self.crs_wkt:
            d["crs_wkt"] = self.crs_wkt
        if self.bbox is not None:
            d["bbox"] = [float(v) for v in self.bbox]
        if self.resolution_m is not None:
            d["resolution_m"] = float(self.resolution_m)
        if self.extra:
            d["extra"] = _sorted_dict(dict(self.extra))
        return d


def _sorted_dict(obj: Any) -> Any:
    """Recursively sort dict keys so canonical JSON is byte-stable."""
    if isinstance(obj, Mapping):
        return {k: _sorted_dict(obj[k]) for k in sorted(obj)}
    if isinstance(obj, (list, tuple)):
        return [_sorted_dict(item) for item in obj]
    return obj


def _sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


class GeographicCache:
    """Read-through cache of geographic artefacts at ``workspace/geographic/``."""

    def __init__(self, workspace_path: str | Path) -> None:
        self._workspace = Path(workspace_path).expanduser().resolve()
        self._root = self._workspace / CACHE_DIRNAME
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        """Directory containing ``<fingerprint>/`` sub-directories."""
        return self._root

    # -- fingerprint ----------------------------------------------------------

    def fingerprint_of(
        self,
        spatial_config: GeographicInputs | Mapping[str, Any],
        *,
        hash_files: bool = True,
    ) -> str:
        """Compute the deterministic fingerprint for a set of spatial inputs.

        ``spatial_config`` may be a :class:`GeographicInputs` instance or a
        plain dict with a compatible subset of keys. When ``hash_files`` is
        ``True`` (default), missing SHA-256 values are derived by streaming
        the referenced file. Paths that do not exist are retained textually —
        this lets consumers compute fingerprints for planned inputs before
        data is downloaded.
        """
        inputs = self._coerce_inputs(spatial_config)

        canonical = inputs.as_canonical_dict()
        if hash_files:
            if "dem_path" in canonical and "dem_sha256" not in canonical:
                h = _maybe_hash(Path(canonical["dem_path"]))
                if h is not None:
                    canonical["dem_sha256"] = h
            if "geology_path" in canonical and "geology_sha256" not in canonical:
                h = _maybe_hash(Path(canonical["geology_path"]))
                if h is not None:
                    canonical["geology_sha256"] = h

        payload = json.dumps(_sorted_dict(canonical), separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # -- cache access ---------------------------------------------------------

    def path_for(self, fingerprint: str) -> Path:
        """Return the directory associated with ``fingerprint``."""
        return self._root / fingerprint

    def is_cached(self, fingerprint: str) -> bool:
        p = self.path_for(fingerprint)
        return p.is_dir() and (p / MANIFEST_FILENAME).is_file()

    def save(
        self,
        fingerprint: str,
        payload_dir: str | Path,
        *,
        manifest: Mapping[str, Any] | None = None,
        overwrite: bool = False,
    ) -> Path:
        """Materialise ``payload_dir`` under ``<cache>/<fingerprint>/``.

        ``payload_dir`` is copied recursively (or merged when ``overwrite``
        is ``False`` and the destination already exists). A ``manifest``
        dict is written alongside the artefacts to make the cache
        self-describing and auditable.
        """
        dst = self.path_for(fingerprint)
        src = Path(payload_dir)
        if not src.is_dir():
            raise FileNotFoundError(f"payload_dir not found: {src}")

        if dst.exists():
            if not overwrite:
                logger.debug("Geographic cache already populated: %s", dst)
            else:
                shutil.rmtree(dst)
        if not dst.exists():
            shutil.copytree(src, dst)

        manifest_path = dst / MANIFEST_FILENAME
        payload = dict(manifest) if manifest else {}
        payload.setdefault("fingerprint", fingerprint)
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return dst

    def load(self, fingerprint: str) -> Path:
        """Return the cached payload directory or raise ``FileNotFoundError``."""
        p = self.path_for(fingerprint)
        if not self.is_cached(fingerprint):
            raise FileNotFoundError(
                f"No geographic cache entry for fingerprint {fingerprint!r} in {self._root}"
            )
        return p

    def list_fingerprints(self) -> list[str]:
        return sorted(
            d.name for d in self._root.iterdir() if d.is_dir() and (d / MANIFEST_FILENAME).is_file()
        )

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _coerce_inputs(
        spec: GeographicInputs | Mapping[str, Any],
    ) -> GeographicInputs:
        if isinstance(spec, GeographicInputs):
            return spec
        allowed = {
            "dem_path",
            "dem_sha256",
            "geology_path",
            "geology_sha256",
            "crs_wkt",
            "bbox",
            "resolution_m",
            "extra",
        }
        leftovers = {k: v for k, v in spec.items() if k not in allowed}
        init_kwargs = {k: v for k, v in spec.items() if k in allowed}
        if leftovers:
            extra = dict(init_kwargs.get("extra") or {})
            extra.update(leftovers)
            init_kwargs["extra"] = extra
        if "bbox" in init_kwargs and init_kwargs["bbox"] is not None:
            init_kwargs["bbox"] = tuple(init_kwargs["bbox"])
        return GeographicInputs(**init_kwargs)


def _maybe_hash(path: Path) -> str | None:
    try:
        if path.is_file():
            return _sha256_file(path)
    except OSError:
        logger.debug("Cannot hash %s", path, exc_info=True)
    return None
