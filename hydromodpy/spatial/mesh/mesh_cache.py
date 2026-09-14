"""Reuse a generated catchment mesh across runs when its inputs are unchanged.

Why this exists
---------------
Gmsh's 2D mesher is not reproducible run to run. Several internal routines reseed
the C library ``rand()`` from the system clock (``srand((unsigned)time(0))`` in
``SOrientedBoundingBox.cpp``, ``meshGFaceLloyd.cpp``, ``meshGFaceRecombine.cpp``,
``Levy3D.cpp``), which overrides the fixed seed set in ``Generator.cpp`` and makes
the Frontal-Delaunay point insertion non-deterministic. The same geometry therefore
yields a slightly different triangulation, and a different cell count, on each run,
so simulation results and calibration objectives are not reproducible.

This was verified empirically on the installed gmsh (4.15): the node count of the
Cheze mesh varies between runs (for example 5304 vs 5245), and none of
``Mesh.RandomSeed`` (already 1 by default), ``General.NumThreads=1``,
``Mesh.MaxNumThreads1D/2D/3D=1``, ``PYTHONHASHSEED=0`` or
``Mesh.Smoothing=0`` + ``Mesh.Optimize=0`` removes it. The reseeding is upstream of
the mesher's ``rand()`` and can only be removed by patching gmsh itself.

The robust fix at this layer is to GENERATE ONCE and REUSE: when the inputs that
determine the mesh (domain geometry, river constraint, lake and dam refinement,
mesh configuration, delineation and buffer configuration) are unchanged, load the
previously generated ``.msh`` instead of regenerating. This keeps the
Frontal-Delaunay quality (the reason it is the chosen algorithm) while making runs
reproducible, which in turn is what a head/stage restart and reproducible
calibration objectives require.

The cache is opt-in (``[mesh_catchment] cache = true``, default off) and fail-safe:
the key hashes only mesh-determining inputs (never physics parameters, so the mesh
is reused across identical-geometry runs), and any key mismatch, missing file or
error falls back to regeneration. A stale mesh is never reused silently.

Sources
-------
- Gmsh mailing list, "Non-deterministic mesh generation due to system-time
  dependent random seeds", https://www.mail-archive.com/gmsh@onelab.info/msg01615.html
- Gmsh issue tracker, https://gitlab.onelab.info/gmsh/gmsh/-/work_items/3005
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_CACHE_KEY_SUFFIX = ".cachekey"
_MESH_FILENAME = "mesh_catchment.msh"
_BUNDLE_DIRNAME = "mesh_catchment_bundle"


def _file_digest(path: object) -> str:
    """SHA-256 of a file's bytes, or empty string when absent."""
    if not path:
        return ""
    file_path = Path(str(path))
    if not file_path.is_file():
        return ""
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_payload(config: object) -> object:
    """Return a JSON-safe dump of a pydantic config, or a repr fallback."""
    dump = getattr(config, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:
            return repr(config)
    return repr(config)


def compute_mesh_cache_key(
    *,
    section_data: object,
    geographic_cfg: object,
    domain_cfg: object,
    constraints_mode: object,
    extra_size_fields: object,
    domain_geographic: object,
) -> str:
    """Hash the inputs that determine the generated mesh (geometry, not physics).

    Only the RAW regional DEM is content-hashed, plus the configuration. The raw DEM
    is the deterministic geometry source (delineation and clipping are deterministic
    functions of it). Derived rasters and shapefiles (the clipped DEM, the watershed
    polygon) are deliberately NOT hashed: they are rewritten every run with fresh
    GeoTIFF/shapefile metadata (creation timestamps, record order) even when the
    geometry is identical, which would make the key vary and the cache never hit. The
    config plus the raw DEM capture every mesh-determining input; ``extra_size_fields``
    carries the lake/dam refinement.
    """
    parts = {
        "mesh_config": _config_payload(section_data),
        "geographic_config": _config_payload(geographic_cfg),
        "domain_config": _config_payload(domain_cfg),
        "constraints_mode": str(constraints_mode),
        "extra_size_fields": repr(extra_size_fields),
        "regional_dem": _file_digest(getattr(domain_geographic, "regional_dem_path", None)),
    }
    payload = json.dumps(parts, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def cached_mesh_paths(mesh_dir: Path) -> tuple[Path, Path, Path]:
    """Return ``(msh, bundle_dir, cachekey)`` inside a mesh output directory."""
    return (
        mesh_dir / _MESH_FILENAME,
        mesh_dir / _BUNDLE_DIRNAME,
        mesh_dir / (_MESH_FILENAME + _CACHE_KEY_SUFFIX),
    )


def mesh_cache_is_valid(mesh_dir: Path, key: str) -> bool:
    """True when a complete mesh whose key matches ``key`` is present."""
    msh, bundle, keyfile = cached_mesh_paths(mesh_dir)
    if not (msh.is_file() and bundle.is_dir() and keyfile.is_file()):
        return False
    try:
        return keyfile.read_text(encoding="utf-8").strip() == key
    except OSError:
        return False


def write_mesh_cache_key(mesh_dir: Path, key: str) -> None:
    """Record the cache key next to the generated mesh (best-effort)."""
    _, _, keyfile = cached_mesh_paths(mesh_dir)
    try:
        keyfile.write_text(key, encoding="utf-8")
    except OSError:
        pass


__all__ = [
    "cached_mesh_paths",
    "compute_mesh_cache_key",
    "mesh_cache_is_valid",
    "write_mesh_cache_key",
]
