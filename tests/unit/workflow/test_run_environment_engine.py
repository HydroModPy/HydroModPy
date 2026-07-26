"""Registration must record the engine the run selected, not a default guess."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.solver.modflow_common.binaries import SolverEngine
from hydromodpy.workflow.steps.prepare_solver import dispatch as dispatch_module


def _ctx(*, runner: str = "subprocess", captured: dict | None = None) -> SimpleNamespace:
    sink = {} if captured is None else captured
    store = SimpleNamespace(
        write_run_environment=lambda sim_id, **kwargs: sink.update({"sim_id": sim_id, **kwargs})
    )
    return SimpleNamespace(
        cfg=SimpleNamespace(
            modflow6=SimpleNamespace(runtime=SimpleNamespace(mf6_runner=runner)),
            simulation=SimpleNamespace(rng_seed=7),
        ),
        setup=SimpleNamespace(
            workspace=SimpleNamespace(project_root=Path("/tmp/project"), bin_path="/tmp/bin")
        ),
        store=store,
    )


def test_execution_mode_follows_the_declared_runner() -> None:
    assert dispatch_module._execution_mode(_ctx(runner="api"), "modflow6") == "api"
    assert dispatch_module._execution_mode(_ctx(runner="subprocess"), "modflow6") == "subprocess"


def test_only_modflow6_can_be_driven_through_the_library() -> None:
    ctx = _ctx(runner="api")

    assert dispatch_module._execution_mode(ctx, "modflow_nwt") == "subprocess"
    assert dispatch_module._execution_mode(ctx, "boussinesq") == "subprocess"
    assert dispatch_module._execution_mode(ctx, None) == "subprocess"


def test_api_registration_records_the_library_engine(monkeypatch) -> None:
    captured: dict = {}
    ctx = _ctx(runner="api", captured=captured)
    engine = SolverEngine(
        solver="modflow6",
        kind="library",
        execution_mode="api",
        path=Path("/tmp/bin/libmf6.so"),
        version="6.6.3",
    )
    monkeypatch.setattr(dispatch_module, "_resolve_solver_engine", lambda *_a, **_k: engine)

    dispatch_module._write_run_environment(ctx, "sim-1", "modflow6")

    assert captured["solver_engine"] == "library"
    assert captured["solver_execution_mode"] == "api"
    assert captured["solver_binary_path"] == Path("/tmp/bin/libmf6.so")
    assert captured["solver_version_text"] == "6.6.3"
    assert captured["rng_seed"] == 7


def test_a_solver_without_an_engine_still_records_its_mode(monkeypatch) -> None:
    """Boussinesq has no binary; the environment row must still be written."""
    captured: dict = {}
    ctx = _ctx(captured=captured)
    monkeypatch.setattr(dispatch_module, "_resolve_solver_engine", lambda *_a, **_k: None)

    dispatch_module._write_run_environment(ctx, "sim-2", "boussinesq")

    assert captured["solver_name"] == "boussinesq"
    assert captured["solver_engine"] is None
    assert captured["solver_binary_path"] is None
    assert captured["solver_execution_mode"] == "subprocess"
