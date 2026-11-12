"""Launcher case of the piecewise strip (heads in m, recharge in m/s).

The run goes through the ``hydromodpy`` command line and reads its result from the catalog.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import validation_cases.shared.boussinesq_piecewise_strip as piecewise
import validation_cases.shared.runtime as runtime


def test_launcher_case_reads_the_catalog_result(monkeypatch, tmp_path):
    out_path = tmp_path / "run"
    store = object()

    def fake_results_dir(*, test_file: str | Path, run_name: str) -> Path:
        assert Path(test_file).name == "case.py"
        assert run_name == "case_boussinesq"
        out_path.mkdir(parents=True, exist_ok=True)
        return out_path

    def fake_run(command, **kwargs):
        assert command[:3] == [piecewise.sys.executable, "-m", "hydromodpy"]
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    def fake_discover_result_store(project_path: Path):
        assert project_path == out_path
        return store, "sim-123"

    model_ws = out_path / "results_simulations" / "flow_validation__boussinesq"
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"

    def fake_resolve_model_workspace(
        project_path: Path,
        *,
        results_folder_name: str,
        model_name: str,
    ):
        assert project_path == out_path
        assert results_folder_name == "results_simulations"
        assert model_name == "flow_validation__boussinesq"
        return model_ws, postprocess_dir, particles_dir

    monkeypatch.setattr(piecewise, "resolve_validation_results_dir", fake_results_dir)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(runtime, "_discover_result_store", fake_discover_result_store)
    monkeypatch.setattr(piecewise, "resolve_model_workspace", fake_resolve_model_workspace)

    result = piecewise.run_piecewise_strip_boussinesq_launcher_case(
        case_dir=tmp_path,
        case_id="case",
        caller_file=tmp_path / "case.py",
        timeout=30,
        process_id="flow_validation",
        simulation_name="case",
        simulation_description="case",
        initial_head_m=6.0,
        west_head_m=5.0,
        east_head_m=5.0,
        recharge_rate_m_s=1.0e-8,
    )

    assert result.store is store
    assert result.sim_id == "sim-123"
    assert result.model_ws == model_ws
    assert result.postprocess_dir == postprocess_dir
    assert not list(out_path.rglob("*.npy"))


def test_launcher_config_keeps_explicit_runtime_settings(tmp_path):
    config_path = piecewise.write_piecewise_strip_launcher_config(
        tmp_path / "run_petsc.toml",
        run_id="petsc_regression",
        process_id="flow_main",
        simulation_name="PETSc regression",
        simulation_description="Explicit PETSc backend fixture",
        bundle_dir=tmp_path / "mesh_bundle",
        initial_head_m=6.0,
        runtime_backend="petsc",
        surface_interaction_model="vi_obstacle",
        apply_runtime_defaults=False,
    )

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert payload["solver"]["boussinesq"]["backend"] == "petsc"
    assert payload["solver"]["boussinesq"]["surface_interaction_model"] == "vi_obstacle"
    assert "runtime" not in payload["flow"]
