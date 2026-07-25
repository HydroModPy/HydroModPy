from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import validation_cases.shared.runtime as runtime
from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR
from validation_cases.shared.loaders import load_case_tolerances, load_time_series_fields
from validation_cases.shared.runtime import (
    resolve_validation_results_dir,
    run_launcher_validation_case,
    write_validation_fields_to_store,
)

MINIMAL_SIMULATION_WORKFLOW = '[workflow]\nmode = "simulation"\n'


@pytest.mark.parametrize(
    ("metadata", "solver", "expected_run_name", "expected_solver_name", "config_files"),
    [
        pytest.param(
            {
                "case_id": "case_demo",
                "config_file": "config_modflownwt.toml",
                "workspace": {},
            },
            None,
            "case_demo",
            "modflow_nwt",
            ("config_modflownwt.toml",),
            id="single-config-file",
        ),
        pytest.param(
            {
                "case_id": "case_demo",
                "default_solver": "modflow_nwt",
                "config_files": {
                    "modflow_nwt": "config_modflownwt.toml",
                    "modflow6": "config_modflow6.toml",
                },
                "workspace": {},
            },
            None,
            "case_demo_modflow_nwt",
            "modflow_nwt",
            ("config_modflownwt.toml", "config_modflow6.toml"),
            id="multi-solver-default",
        ),
        pytest.param(
            {
                "case_id": "case_demo",
                "default_solver": "modflow_nwt",
                "config_files": {
                    "modflow_nwt": "config_modflownwt.toml",
                },
                "workspace": {},
            },
            None,
            "case_demo",
            "modflow_nwt",
            ("config_modflownwt.toml",),
            id="single-entry-config-mapping",
        ),
        pytest.param(
            {
                "case_id": "case_demo",
                "default_solver": "modflow_nwt",
                "config_files": {
                    "modflow_nwt": "config_modflownwt.toml",
                    "modflow6": "config_modflow6.toml",
                },
                "workspace": {},
            },
            "modflow6",
            "case_demo_modflow6",
            "modflow6",
            ("config_modflownwt.toml", "config_modflow6.toml"),
            id="explicit-solver",
        ),
    ],
)
def test_run_launcher_validation_case_resolves_solver_name_and_output_run_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    metadata: dict,
    solver: str | None,
    expected_run_name: str,
    expected_solver_name: str,
    config_files: tuple[str, ...],
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    for config_file in config_files:
        (case_dir / config_file).write_text(MINIMAL_SIMULATION_WORKFLOW, encoding="utf-8")

    captured: dict[str, str] = {}

    def _resolve_results_dir(*, test_file, run_name):
        del test_file
        captured["run_name"] = run_name
        return tmp_path / "outputs"

    monkeypatch.setattr(
        "validation_cases.shared.runtime.load_case_metadata",
        lambda _case_dir: metadata,
    )
    monkeypatch.setattr(
        "validation_cases.shared.runtime.resolve_validation_results_dir",
        _resolve_results_dir,
    )

    def _fake_subprocess_run(*args, **kwargs):
        del args
        captured["auto_register"] = kwargs["env"].get("HMP_AUTO_REGISTER_WORKSPACE")
        return SimpleNamespace(
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(
        "validation_cases.shared.runtime.subprocess.run",
        _fake_subprocess_run,
    )
    model_ws = tmp_path / "outputs" / "watershed" / "results_simulations" / "model"
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    monkeypatch.setattr(
        "validation_cases.shared.runtime.resolve_model_workspace",
        lambda *args, **kwargs: (model_ws, postprocess_dir, particles_dir),
    )

    result = run_launcher_validation_case(case_dir=case_dir, test_file=__file__, solver=solver)

    assert captured["run_name"] == expected_run_name
    assert captured["auto_register"] == "0"
    assert result.solver_name == expected_solver_name
    assert result.model_ws == model_ws


@pytest.mark.parametrize(
    ("run_name", "expected_dir_name"),
    [
        pytest.param(
            "dupuit_fixed_head_1d_modflownwt",
            "dupuit_fixed_head_cb0dd6cf67",
            id="long-modflownwt-name",
        ),
        pytest.param(
            "dupuit_fixed_head_1d_modflow6",
            "dupuit_fixed_head_ec0532fa37",
            id="long-modflow6-name",
        ),
        pytest.param(
            "case_demo_modflownwt",
            "case_demo_modflownwt",
            id="short-name-kept",
        ),
    ],
)
def test_resolve_validation_results_dir_uses_deterministic_solver_specific_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    run_name: str,
    expected_dir_name: str,
) -> None:
    monkeypatch.setattr(runtime, "_WINDOWS_VALIDATION_PATH_LIMIT", 10_000)
    out_root = tmp_path / "validation_root"
    monkeypatch.setenv("HMP_OUT_PATH", str(out_root))

    out_dir = resolve_validation_results_dir(
        test_file=tmp_path / "test_dupuit_fixed_head_1d.py",
        run_name=run_name,
    )

    assert out_dir == (
        out_root.resolve() / "validation" / "test_dupuit_fixed_head_1d" / expected_dir_name
    )


def test_resolve_validation_results_dir_reuses_existing_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runtime, "_WINDOWS_VALIDATION_PATH_LIMIT", 10_000)
    out_root = tmp_path / "validation_root"
    monkeypatch.setenv("HMP_OUT_PATH", str(out_root))

    out_dir = resolve_validation_results_dir(
        test_file=tmp_path / "test_dupuit_fixed_head_1d.py",
        run_name="case_demo",
    )
    out_dir.mkdir(parents=True)
    stale_file = out_dir / "stale-output.txt"
    stale_file.write_text("stale", encoding="utf-8")
    stale_out_dir = out_dir.with_name(f"{out_dir.name}_deadbeef")
    stale_out_dir.mkdir()
    (stale_out_dir / "old-output.txt").write_text("old", encoding="utf-8")

    resolved_again = resolve_validation_results_dir(
        test_file=tmp_path / "test_dupuit_fixed_head_1d.py",
        run_name="case_demo",
    )

    assert resolved_again == out_dir
    assert not stale_file.exists()
    assert not stale_out_dir.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows path budget regression")
def test_resolve_validation_results_dir_falls_back_from_long_windows_output_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    long_root = tmp_path / ("root_" + "x" * 60) / ("nested_" + "y" * 60)
    monkeypatch.setenv("HMP_OUT_PATH", str(long_root))

    out_dir = resolve_validation_results_dir(
        test_file=tmp_path / "test_dupuit_fixed_head_1d.py",
        run_name="dupuit_fixed_head_1d_modflow6",
    )

    assert long_root.resolve() not in out_dir.parents
    scratch_probe = out_dir / PREPROCESSING_DIR / "geographic"
    assert len(str(scratch_probe)) < runtime._WINDOWS_VALIDATION_PATH_LIMIT


def test_load_case_tolerances_prefers_solver_specific_file(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "tolerances.toml").write_text(
        "[head_profile]\nrmse = 0.01\n",
        encoding="utf-8",
    )
    (case_dir / "tolerances_modflow6.toml").write_text(
        "[head_profile]\nrmse = 0.05\n",
        encoding="utf-8",
    )
    (case_dir / "tolerances_modflownwt.toml").write_text(
        "[head_profile]\nrmse = 0.03\n",
        encoding="utf-8",
    )

    tolerances = load_case_tolerances(case_dir, solver="modflow6")
    nwt_tolerances = load_case_tolerances(case_dir, solver="modflow_nwt")
    fallback_tolerances = load_case_tolerances(case_dir, solver="unknown_solver")

    assert float(tolerances["head_profile"]["rmse"]) == pytest.approx(0.05)
    assert float(nwt_tolerances["head_profile"]["rmse"]) == pytest.approx(0.03)
    assert float(fallback_tolerances["head_profile"]["rmse"]) == pytest.approx(0.01)


def test_validation_launcher_config_requires_explicit_workflow(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    config_path = case_dir / "config_modflownwt.toml"
    config_path.write_text('[simulation]\nname = "missing workflow"\n', encoding="utf-8")
    (case_dir / "metadata.toml").write_text(
        'case_id = "case_demo"\nconfig_file = "config_modflownwt.toml"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must define \\[workflow\\]"):
        runtime._build_validation_launcher_config(
            case_dir=case_dir,
            config_path=config_path,
            solver_name="modflow_nwt",
        )


def test_run_launcher_validation_case_reports_failure_even_when_outputs_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "config_modflownwt.toml").write_text(
        MINIMAL_SIMULATION_WORKFLOW,
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "validation_cases.shared.runtime.load_case_metadata",
        lambda _case_dir: {
            "case_id": "case_demo",
            "config_file": "config_modflownwt.toml",
            "workspace": {},
        },
    )
    monkeypatch.setattr(
        "validation_cases.shared.runtime.resolve_validation_results_dir",
        lambda **kwargs: tmp_path / "outputs",
    )
    monkeypatch.setattr(
        "validation_cases.shared.runtime.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="partial run",
            stderr="solver did not converge",
        ),
    )
    model_ws = tmp_path / "outputs" / "watershed" / "results_simulations" / "model"
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    particles_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "validation_cases.shared.runtime.resolve_model_workspace",
        lambda *args, **kwargs: (model_ws, postprocess_dir, particles_dir),
    )

    with pytest.raises(AssertionError, match="hydromodpy.__main__ failed") as excinfo:
        run_launcher_validation_case(case_dir=case_dir, test_file=__file__)

    message = str(excinfo.value)
    assert "partial run" in message
    assert "solver did not converge" in message
    assert model_ws.exists()


def test_run_launcher_validation_case_reports_subprocess_failure_when_outputs_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "config_modflownwt.toml").write_text(
        MINIMAL_SIMULATION_WORKFLOW,
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "validation_cases.shared.runtime.load_case_metadata",
        lambda _case_dir: {
            "case_id": "case_demo",
            "config_file": "config_modflownwt.toml",
            "workspace": {},
        },
    )
    monkeypatch.setattr(
        "validation_cases.shared.runtime.resolve_validation_results_dir",
        lambda **kwargs: tmp_path / "outputs",
    )
    monkeypatch.setattr(
        "validation_cases.shared.runtime.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="partial run",
            stderr="solver did not converge",
        ),
    )
    monkeypatch.setattr(
        "validation_cases.shared.runtime.resolve_model_workspace",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Model folder not found")),
    )

    with pytest.raises(AssertionError, match="hydromodpy.__main__ failed"):
        run_launcher_validation_case(case_dir=case_dir, test_file=__file__)


def test_write_validation_fields_to_store_writes_gridded_series(tmp_path: Path) -> None:
    fields = {
        "watertable_elevation": {
            0: np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=float),
            1: np.asarray([[5.0, 6.0], [7.0, 8.0]], dtype=float),
        },
        "watertable_depth": {
            0: np.asarray([[9.0, 8.0], [7.0, 6.0]], dtype=float),
            1: np.asarray([[5.0, 4.0], [3.0, 2.0]], dtype=float),
        },
    }

    store, sim_id = write_validation_fields_to_store(
        out_path=tmp_path,
        fields=fields,
        solver_name="boussinesq",
        flow_regime="transient",
    )
    try:
        assert sim_id is not None
        geo_meta = store.read_geographic_metadata(sim_id)
        assert int(geo_meta["nrow"]) == 2
        assert int(geo_meta["ncol"]) == 2

        indices, arrays = load_time_series_fields(
            store=store,
            sim_id=sim_id,
            observable_name="watertable_elevation",
            expected_spatial_shape=(2, 2),
        )

        np.testing.assert_array_equal(indices, np.asarray([0, 1], dtype=int))
        np.testing.assert_allclose(
            arrays,
            np.asarray(
                [
                    [[1.0, 2.0], [3.0, 4.0]],
                    [[5.0, 6.0], [7.0, 8.0]],
                ],
                dtype=float,
            ),
        )
    finally:
        if store is not None:
            store.close()
