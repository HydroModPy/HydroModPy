"""The engine a run records must be the one it executed.

An ``api`` run solves through ``libmf6``; recording the ``mf6`` executable
instead makes the provenance sha256 and version describe a file the solve never
opened. These checks pin the resolution and its two failure modes.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.solver.modflow_common import binaries


def _stub_engine_files(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    exe = tmp_path / "mf6"
    lib = tmp_path / "libmf6.so"
    exe.write_bytes(b"exe")
    lib.write_bytes(b"lib")
    monkeypatch.setattr(binaries, "ensure_solver_binary", lambda *_a, **_k: exe)
    monkeypatch.setattr(binaries, "ensure_solver_library", lambda *_a, **_k: lib)
    monkeypatch.setattr(binaries, "mf6_executable_version", lambda _p: "6.6.3")
    monkeypatch.setattr(binaries, "libmf6_version", lambda _p: "6.6.3")
    return exe, lib


def test_api_mode_resolves_the_shared_library(monkeypatch, tmp_path: Path) -> None:
    _, lib = _stub_engine_files(monkeypatch, tmp_path)

    engine = binaries.resolve_solver_engine("modflow6", execution_mode="api")

    assert engine is not None
    assert engine.kind == "library"
    assert engine.execution_mode == "api"
    assert engine.path == lib
    assert engine.version == "6.6.3"


def test_subprocess_mode_resolves_the_executable(monkeypatch, tmp_path: Path) -> None:
    exe, _ = _stub_engine_files(monkeypatch, tmp_path)

    engine = binaries.resolve_solver_engine("modflow6", execution_mode="subprocess")

    assert engine is not None
    assert engine.kind == "executable"
    assert engine.execution_mode == "subprocess"
    assert engine.path == exe


def test_api_mode_on_a_non_mf6_solver_falls_back_to_its_executable(
    monkeypatch, tmp_path: Path
) -> None:
    """Only MODFLOW 6 ships a shared library; NWT keeps its executable."""
    exe, _ = _stub_engine_files(monkeypatch, tmp_path)

    engine = binaries.resolve_solver_engine("modflow_nwt", execution_mode="api")

    assert engine is not None
    assert engine.kind == "executable"
    assert engine.execution_mode == "subprocess"
    assert engine.path == exe


def test_solver_without_a_bundled_binary_has_no_engine() -> None:
    assert binaries.resolve_solver_engine("boussinesq") is None
    assert binaries.resolve_solver_engine("gr4j", execution_mode="api") is None


def test_an_unresolvable_engine_never_raises(monkeypatch) -> None:
    """Provenance must never be the reason a run refuses to start."""

    def boom(*_args, **_kwargs):
        raise FileNotFoundError("no binary here")

    monkeypatch.setattr(binaries, "ensure_solver_binary", boom)
    monkeypatch.setattr(binaries, "ensure_solver_library", boom)

    assert binaries.resolve_solver_engine("modflow6") is None
    assert binaries.resolve_solver_engine("modflow6", execution_mode="api") is None
