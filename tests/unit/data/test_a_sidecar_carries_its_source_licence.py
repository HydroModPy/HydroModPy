"""A raw input's sidecar states the licence of its source.

``Sidecar.license`` was null in every real sidecar: its single construction
site never passed it. It now comes from the source registry, and a licence the
user declared for the same bytes survives a rewrite.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.data.registry.cache_store import emit_input_sidecar
from hydromodpy.data.sidecars import Sidecar, load_sidecar, write_sidecar


def _raw(tmp_path: Path) -> Path:
    path = tmp_path / "geology.gpkg"
    path.write_bytes(b"geology")
    return path


def _emit(path: Path, source: str, sha256: str = "abc") -> Sidecar:
    emit_input_sidecar(path, sha256=sha256, source=source, crs=None, bbox=(None,) * 4)
    return load_sidecar(path)


def test_a_known_source_stamps_its_licence(tmp_path: Path) -> None:
    assert _emit(_raw(tmp_path), "brgm_1m").license == "etalab-2.0"


def test_a_user_file_is_stamped_undetermined(tmp_path: Path) -> None:
    assert _emit(_raw(tmp_path), "custom").license == UNDETERMINED_LICENSE


def test_a_declared_licence_survives_a_rewrite_of_the_same_bytes(tmp_path: Path) -> None:
    path = _raw(tmp_path)
    write_sidecar(path, Sidecar(source="custom", sha256="abc", license="CC0-1.0"))
    assert _emit(path, "custom").license == "CC0-1.0"


def test_a_declared_licence_does_not_follow_new_bytes(tmp_path: Path) -> None:
    path = _raw(tmp_path)
    write_sidecar(path, Sidecar(source="custom", sha256="abc", license="CC0-1.0"))
    assert _emit(path, "custom", sha256="def").license == UNDETERMINED_LICENSE
