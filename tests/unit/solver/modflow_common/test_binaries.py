"""A solver reaches ``bin_path`` only from a zip that hashes to the digest of its release."""

from __future__ import annotations

import io
import os
import re
import sys
import zipfile
from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import exit_code_for
from hydromodpy.cli.main import main as cli_main
from hydromodpy.core.exceptions import CacheCorruptionError, NetworkError, SolverBinaryError
from hydromodpy.solver.modflow_common import binaries
from tests.unit.core.io._fake_release import digest_of, serve_assets

ASSET = binaries._release_asset()


def _zip_of(*solvers: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("code.json", "{}")
        for solver in solvers:
            bundle.writestr(binaries.exe_filename(solver), f"the {solver} build")
    return buffer.getvalue()


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "cache"
    monkeypatch.setattr(binaries, "cache_dir", lambda: folder)
    return folder


def _pin(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> str:
    digest = digest_of(payload)
    monkeypatch.setitem(binaries.RELEASE_ASSETS["23.0"], ASSET, digest)
    return digest


def test_named_solvers_land(cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _zip_of("mf6", "mfnwt", "libmf6")
    digest = _pin(monkeypatch, payload)
    asked = serve_assets(monkeypatch, {ASSET: payload})
    target = tmp_path / "bin"

    assert binaries.download_solver_binaries(target, subset=["mf6"]) == target

    assert (target / binaries.exe_filename("mf6")).read_text() == "the mf6 build"
    assert not (target / binaries.exe_filename("mfnwt")).exists()
    assert not (target / "code.json").exists()
    assert not list(target.glob(".*.part"))
    if os.name == "posix":
        assert os.access(target / "mf6", os.X_OK)
    assert asked == [binaries.asset_url("23.0", ASSET)]
    manifest = binaries.read_manifest(target)
    assert manifest is not None
    assert manifest["release"] == "23.0"
    assert manifest["solvers"] == ["mf6"]
    assert manifest["asset"] == ASSET
    assert manifest["asset_sha256"] == digest


def test_subset_cache_and_force(
    cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _zip_of("mf6", "mfnwt")
    _pin(monkeypatch, payload)
    asked = serve_assets(monkeypatch, {ASSET: payload})
    target = tmp_path / "bin"

    binaries.download_solver_binaries(target, subset=["mf6"])
    binaries.download_solver_binaries(target, subset=["mfnwt"])
    assert len(asked) == 1
    assert binaries.read_manifest(target)["solvers"] == ["mf6", "mfnwt"]

    binaries.download_solver_binaries(target, subset=["mf6"], force=True)
    assert len(asked) == 2
    assert binaries.read_manifest(target)["solvers"] == ["mf6"]


def test_wrong_digest_refused(cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pinned = _pin(monkeypatch, b"the zip of the release")
    payload = _zip_of("mf6")
    serve_assets(monkeypatch, {ASSET: payload})
    target = tmp_path / "bin"

    with pytest.raises(CacheCorruptionError) as refused:
        binaries.download_solver_binaries(target, subset=["mf6"])

    message = str(refused.value)
    assert pinned in message
    assert digest_of(payload) in message
    assert "HMP_BIN" in message
    assert not (target / binaries.exe_filename("mf6")).exists()
    assert binaries.read_manifest(target) is None


def test_lazy_path_refuses_too(
    cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin(monkeypatch, b"the zip of the release")
    serve_assets(monkeypatch, {ASSET: _zip_of("mf6")})
    monkeypatch.setattr(binaries, "resolve_bin_path", lambda: str(cache / "bin"))

    with pytest.raises(CacheCorruptionError):
        binaries.ensure_solver_binary("mf6")


def test_hmp_bin_never_filled(cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "shared_bin"
    folder.mkdir()
    monkeypatch.setattr(binaries, "resolve_bin_path", lambda: str(folder))
    _pin(monkeypatch, b"the zip of the release")
    served = serve_assets(monkeypatch, {ASSET: _zip_of("mf6")})

    expected = binaries.ensure_solver_binary("mf6")

    assert expected.parent == folder
    assert not expected.exists()
    assert not binaries.is_managed_cache(folder)
    assert not (cache / "bin").exists()
    assert served == []


@pytest.mark.parametrize("release", ["24.0", "latest"])
def test_unpinned_release_refused(
    cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, release: str
) -> None:
    asked = serve_assets(monkeypatch, {})

    with pytest.raises(SolverBinaryError) as refused:
        binaries.download_solver_binaries(tmp_path / "bin", subset=["mf6"], release=release)

    message = str(refused.value)
    assert release in message
    assert binaries.DEFAULT_RELEASE in message
    assert "get-modflow" in message
    assert "HMP_BIN" in message
    assert asked == []


def test_missing_solver_refused(
    cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _zip_of("mf6")
    _pin(monkeypatch, payload)
    serve_assets(monkeypatch, {ASSET: payload})

    with pytest.raises(SolverBinaryError, match=binaries.exe_filename("mp7")):
        binaries.download_solver_binaries(tmp_path / "bin", subset=["mp7"])


def test_default_release_digests() -> None:
    pinned = binaries.RELEASE_ASSETS[binaries.DEFAULT_RELEASE]

    assert set(pinned) == {"linux.zip", "mac.zip", "macarm.zip", "win64.zip"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in pinned.values())


@pytest.mark.parametrize(
    ("system", "machine", "asset"),
    [
        ("linux", "x86_64", "linux.zip"),
        ("darwin", "x86_64", "mac.zip"),
        ("darwin", "arm64", "macarm.zip"),
        ("win32", "AMD64", "win64.zip"),
    ],
)
def test_zip_of_each_platform(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, asset: str
) -> None:
    monkeypatch.setattr(binaries.sys, "platform", system)
    monkeypatch.setattr(binaries.platform, "machine", lambda: machine)

    assert binaries._release_asset() == asset


@pytest.mark.parametrize(
    "raised",
    [
        CacheCorruptionError("hashes to a, pins b"),
        SolverBinaryError("no digest for release 24.0"),
        NetworkError("could not download"),
    ],
)
def test_command_refusal_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    raised: Exception,
) -> None:
    def refuse(**_kwargs: object) -> None:
        raise raised

    monkeypatch.setattr(binaries, "download_solver_binaries", refuse)
    args = ["install-binaries", "--subset", "mf6", "--to", str(tmp_path), "-q"]

    with pytest.raises(SystemExit) as stopped:
        cli_main(args)

    assert stopped.value.code == exit_code_for(raised)
    assert str(raised) in capsys.readouterr().err


def test_python_stack_of_a_missing_wrapper(monkeypatch) -> None:
    # A None entry in sys.modules makes the import of that wrapper fail.
    monkeypatch.setitem(sys.modules, "modflowapi", None)
    stack = binaries.solver_python_stack()
    assert stack.startswith("modflowapi (absent), xmipy")
