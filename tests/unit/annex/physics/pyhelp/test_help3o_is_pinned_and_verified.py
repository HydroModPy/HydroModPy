"""HELP3O is native code: only an extension that hashes to its pin is ever loaded."""

from __future__ import annotations

import io
import re
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import CacheCorruptionError
from hydromodpy_annex.physics.pyhelp.core import paths
from tests.unit.core.io._fake_release import serve_assets

COVERED = [
    (system, machine, minor)
    for system, machine in (
        ("Linux", "x86_64"),
        ("Darwin", "arm64"),
        ("Darwin", "x86_64"),
        ("Windows", "AMD64"),
    )
    for minor in (11, 12, 13)
]


def _on(monkeypatch: pytest.MonkeyPatch, system: str, machine: str, minor: int) -> None:
    """Make the module read another platform and Python version."""
    monkeypatch.setattr(
        paths, "platform", SimpleNamespace(system=lambda: system, machine=lambda: machine)
    )
    monkeypatch.setattr(
        paths,
        "sys",
        SimpleNamespace(version_info=SimpleNamespace(major=3, minor=minor), platform=sys.platform),
    )


def _names(system: str, machine: str, minor: int, monkeypatch: pytest.MonkeyPatch) -> str:
    _on(monkeypatch, system, machine, minor)
    return paths._asset_filename(paths._get_binary_filename())


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    folder = tmp_path / "cache"
    monkeypatch.setattr(paths, "_hmp_cache_dir", lambda: folder)
    monkeypatch.setattr(paths, "HELP3O", None)
    yield folder / "help3o" / paths.HELP3O_RELEASE


@pytest.fixture
def loaded(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Record what would be loaded, in place of the native load."""
    seen: list[Path] = []

    def load(path: Path) -> SimpleNamespace:
        seen.append(Path(path))
        return SimpleNamespace(path=path)

    monkeypatch.setattr(paths, "_load_help3o_from_path", load)
    return seen


def test_the_table_is_what_the_platforms_ask_for(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = {_names(*combination, monkeypatch) for combination in COVERED}

    assert asked == set(paths.HELP3O_ASSETS)
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in paths.HELP3O_ASSETS.values())
    assert "bastien-boivin" not in paths.HELP3O_BINARIES_REPO
    assert "latest" not in paths.HELP3O_RELEASE


def _linux_asset(monkeypatch: pytest.MonkeyPatch) -> str:
    _on(monkeypatch, "Linux", "x86_64", 13)
    return "HELP3O.cpython-313-x86_64-linux-gnu.so"


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, payload in members.items():
            bundle.writestr(name, payload)
    return buffer.getvalue()


def test_a_bundle_changed_in_the_cache_is_refused(
    cache: Path, loaded: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _on(monkeypatch, "Windows", "AMD64", 12)
    cache.mkdir(parents=True)
    (cache / "HELP3O.cp312-win_amd64_bundle.zip").write_bytes(b"changed on disk")
    serve_assets(monkeypatch, {})

    with pytest.raises(CacheCorruptionError):
        paths.ensure_help3o_loaded()

    assert loaded == []
