"""Unit tests for the catchment-mesh reuse cache.

The cache exists because gmsh is not reproducible run to run; see
``hydromodpy.spatial.mesh.mesh_cache`` for the rationale and sources.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.mesh.mesh_cache import (
    cached_mesh_paths,
    compute_mesh_cache_key,
    mesh_cache_is_valid,
    write_mesh_cache_key,
)


class _Cfg:
    """Minimal pydantic-like stub exposing ``model_dump``."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self, mode: str | None = None) -> dict:
        return dict(self._payload)


class _DomainGeographic:
    def __init__(self, regional_dem_path: str | None) -> None:
        self.regional_dem_path = regional_dem_path


def _key(section=None, geographic=None, domain=None, mode="rivers_only", fields=(), dem=None):
    return compute_mesh_cache_key(
        section_data=section or _Cfg({"size": 80}),
        geographic_cfg=geographic or _Cfg({"extent": "watershed"}),
        domain_cfg=domain or _Cfg({"buffer": 10}),
        constraints_mode=mode,
        extra_size_fields=fields,
        domain_geographic=_DomainGeographic(dem),
    )


def test_cache_key_is_stable_for_identical_inputs() -> None:
    assert _key() == _key()


def test_cache_key_changes_when_a_config_input_changes() -> None:
    base = _key()
    assert _key(section=_Cfg({"size": 60})) != base
    assert _key(mode="rivers_and_lakes") != base
    assert _key(fields=("shoreline",)) != base


def test_cache_key_tracks_the_raw_dem_content(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"elevation-a")
    key_a = _key(dem=str(dem))
    dem.write_bytes(b"elevation-b")
    key_b = _key(dem=str(dem))
    assert key_a != key_b
    # A missing DEM path is tolerated (empty digest), not an error.
    assert _key(dem=None) == _key(dem=str(tmp_path / "absent.tif"))


def test_mesh_cache_is_valid_requires_all_artifacts(tmp_path: Path) -> None:
    assert mesh_cache_is_valid(tmp_path, "k") is False  # nothing present
    msh, bundle, _ = cached_mesh_paths(tmp_path)
    msh.write_text("mesh")
    bundle.mkdir()
    assert mesh_cache_is_valid(tmp_path, "k") is False  # no key file yet
    write_mesh_cache_key(tmp_path, "k")
    assert mesh_cache_is_valid(tmp_path, "k") is True
    assert mesh_cache_is_valid(tmp_path, "other") is False  # key mismatch -> regenerate
