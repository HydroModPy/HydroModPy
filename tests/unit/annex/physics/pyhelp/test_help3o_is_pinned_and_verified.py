"""HELP3O is native code: only an extension that hashes to its pin is ever loaded."""

from __future__ import annotations

import io
import pickle
import re
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import CacheCorruptionError, NetworkError, SolverBinaryError
from hydromodpy_annex.physics.pyhelp.core import paths, processing
from tests.unit.core.io._fake_release import digest_of, serve_assets

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


@pytest.mark.parametrize(
    ("system", "machine", "minor"),
    [
        ("Linux", "x86_64", 14),
        ("Linux", "aarch64", 12),
        ("Darwin", "arm64", 14),
        ("Windows", "ARM64", 13),
        ("Windows", "AMD64", 10),
        ("FreeBSD", "amd64", 12),
    ],
)
def test_a_combination_the_release_does_not_cover_is_refused_before_any_download(
    cache: Path,
    loaded: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    minor: int,
) -> None:
    asked = serve_assets(monkeypatch, {})
    _on(monkeypatch, system, machine, minor)

    with pytest.raises(SolverBinaryError) as refused:
        paths.ensure_help3o_loaded()

    message = str(refused.value)
    assert f"Python 3.{minor}" in message
    assert system in message
    assert machine in message
    assert paths.HELP3O_RELEASE in message
    assert "Python 3.11, 3.12 and 3.13" in message
    assert asked == []
    assert loaded == []


def _linux_asset(monkeypatch: pytest.MonkeyPatch) -> str:
    _on(monkeypatch, "Linux", "x86_64", 13)
    return "HELP3O.cpython-313-x86_64-linux-gnu.so"


def test_the_extension_loads_from_the_pinned_tag_once_it_passes(
    cache: Path, loaded: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _linux_asset(monkeypatch)
    payload = b"the extension"
    monkeypatch.setitem(paths.HELP3O_ASSETS, asset, digest_of(payload))
    asked = serve_assets(monkeypatch, {asset: payload})

    assert paths.ensure_help3o_loaded() is paths.ensure_help3o_loaded()

    assert loaded == [cache / asset]
    assert asked == [
        f"https://github.com/HydroModPy/HELP3O-binaries/releases/download/"
        f"{paths.HELP3O_RELEASE}/{asset}"
    ]


def test_other_bytes_are_never_loaded_and_the_error_names_both_digests(
    cache: Path, loaded: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _linux_asset(monkeypatch)
    payload = b"not the extension"
    serve_assets(monkeypatch, {asset: payload})

    with pytest.raises(CacheCorruptionError) as refused:
        paths.ensure_help3o_loaded()

    assert paths.HELP3O_ASSETS[asset] in str(refused.value)
    assert digest_of(payload) in str(refused.value)
    assert asset in str(refused.value)
    assert loaded == []
    assert not (cache / asset).exists()


def test_an_extension_changed_in_the_cache_is_never_loaded(
    cache: Path, loaded: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _linux_asset(monkeypatch)
    cache.mkdir(parents=True)
    (cache / asset).write_bytes(b"changed on disk")
    asked = serve_assets(monkeypatch, {})

    with pytest.raises(CacheCorruptionError, match=digest_of(b"changed on disk")):
        paths.ensure_help3o_loaded()

    assert loaded == []
    assert asked == []


def test_a_flat_extension_of_an_older_install_is_never_read(
    cache: Path, loaded: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _linux_asset(monkeypatch)
    old = cache.parents[1] / asset
    old.parent.mkdir(parents=True)
    old.write_bytes(b"unpinned, from releases/latest")
    payload = b"the extension"
    monkeypatch.setitem(paths.HELP3O_ASSETS, asset, digest_of(payload))
    serve_assets(monkeypatch, {asset: payload})

    paths.ensure_help3o_loaded()

    assert loaded == [cache / asset]


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


@pytest.mark.parametrize(
    ("system", "machine", "extension", "library", "pack"),
    [
        ("Darwin", "arm64", "HELP3O.cpython-313-macosx_arm64.so", "libgfortran.5.dylib", _tar_gz),
        ("Windows", "AMD64", "HELP3O.cp313-win_amd64.pyd", "libgfortran-5.dll", _zip),
    ],
    ids=["macos", "windows"],
)
def test_a_bundle_is_unpacked_from_its_verified_archive_on_every_load(
    cache: Path,
    loaded: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    extension: str,
    library: str,
    pack,
) -> None:
    _on(monkeypatch, system, machine, 13)
    asset = paths._asset_filename(extension)
    members = {extension: b"the extension", library: b"the runtime"}
    payload = pack(members)
    monkeypatch.setitem(paths.HELP3O_ASSETS, asset, digest_of(payload))
    asked = serve_assets(monkeypatch, {asset: payload})

    paths.ensure_help3o_loaded()

    folder = cache / Path(extension).stem
    assert loaded == [folder / extension]
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == members

    # A member changed on disk goes back to the bytes of the archive, with no download.
    (folder / library).write_bytes(b"planted")
    (folder / extension).unlink()
    monkeypatch.setattr(paths, "HELP3O", None)
    paths.ensure_help3o_loaded()
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == members
    assert len(asked) == 1


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


def test_a_network_failure_says_where_to_place_the_file_by_hand(
    cache: Path, loaded: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _linux_asset(monkeypatch)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise NetworkError("HTTP GET x failed", last_exception="Connection refused")

    monkeypatch.setattr(paths, "fetch_pinned", refuse)

    with pytest.raises(NetworkError) as caught:
        paths.ensure_help3o_loaded()

    message = str(caught.value)
    assert asset in message
    assert "Connection refused" in message
    assert "HTTPS_PROXY" in message
    assert str(cache) in message
    assert loaded == []


@pytest.mark.skipif(sys.platform != "linux", reason="writes bytes under the name of a .so")
def test_an_extension_that_passes_but_does_not_load_is_refused_by_name(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _linux_asset(monkeypatch)
    payload = b"not an elf file"
    monkeypatch.setitem(paths.HELP3O_ASSETS, asset, digest_of(payload))
    serve_assets(monkeypatch, {asset: payload})

    with pytest.raises(SolverBinaryError, match=re.escape(str(cache / asset))):
        paths.ensure_help3o_loaded()


def test_a_run_stops_on_the_refusal_before_it_opens_a_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = SolverBinaryError("no pinned build")

    def refuse() -> None:
        raise refusal

    monkeypatch.setattr(processing, "ensure_help3o_loaded", refuse)
    monkeypatch.setattr(processing.mp, "get_context", lambda *_a: pytest.fail("opened a pool"))

    with pytest.raises(SolverBinaryError):
        processing.run_help_allcells({"cell": ()})
    with pytest.raises(SolverBinaryError):
        processing.run_help_singlecell(("cell", ()))

    # A spawn worker hands its refusal back to the parent through pickle.
    assert str(pickle.loads(pickle.dumps(refusal))) == "no pinned build"
