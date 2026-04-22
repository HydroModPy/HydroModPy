from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from validation_cases.shared.loaders import load_case_tolerances
from validation_cases.shared.runtime import (
    resolve_validation_results_dir,
    run_launcher_validation_case,
)


@pytest.mark.parametrize(
    ("metadata", "solver", "expected_run_name", "expected_solver_name", "config_files"),
    [
        pytest.param(
            {
                "case_id": "case_demo",
                "launcher": "launcher_simulation",
                "config_file": "config_modflownwt.toml",
                "workspace": {},
            },
            None,
            "case_demo",
            "modflownwt",
            ("config_modflownwt.toml",),
            id="legacy-single-config",
        ),
        pytest.param(
            {
                "case_id": "case_demo",
                "launcher": "launcher_simulation",
                "default_solver": "modflownwt",
                "config_files": {
                    "modflownwt": "config_modflownwt.toml",
                    "modflow6": "config_modflow6.toml",
                },
                "workspace": {},
            },
            None,
            "case_demo_modflownwt",
            "modflownwt",
            ("config_modflownwt.toml", "config_modflow6.toml"),
            id="multi-solver-default",
        ),
        pytest.param(
            {
                "case_id": "case_demo",
                "launcher": "launcher_simulation",
                "default_solver": "modflownwt",
                "config_files": {
                    "modflownwt": "config_modflownwt.toml",
                },
                "workspace": {},
            },
            None,
            "case_demo",
            "modflownwt",
            ("config_modflownwt.toml",),
            id="single-entry-config-mapping",
        ),
        pytest.param(
            {
                "case_id": "case_demo",
                "launcher": "launcher_simulation",
                "default_solver": "modflownwt",
                "config_files": {
                    "modflownwt": "config_modflownwt.toml",
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
        (case_dir / config_file).write_text("", encoding="utf-8")

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
    monkeypatch.setattr(
        "validation_cases.shared.runtime.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="ok",
            stderr="",
        ),
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
    out_root = tmp_path / "validation_root"
    monkeypatch.setenv("HYDROMODPY_OUT_PATH", str(out_root))

    out_dir = resolve_validation_results_dir(
        test_file=tmp_path / "test_dupuit_fixed_head_1d.py",
        run_name=run_name,
    )

    assert out_dir == (
        out_root.resolve() / "validation" / "test_dupuit_fixed_head_1d" / expected_dir_name
    )


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

    tolerances = load_case_tolerances(case_dir, solver="modflow6")
    fallback_tolerances = load_case_tolerances(case_dir, solver="modflownwt")

    assert float(tolerances["head_profile"]["rmse"]) == pytest.approx(0.05)
    assert float(fallback_tolerances["head_profile"]["rmse"]) == pytest.approx(0.01)


def test_run_launcher_validation_case_reports_failure_even_when_outputs_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "config_modflownwt.toml").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "validation_cases.shared.runtime.load_case_metadata",
        lambda _case_dir: {
            "case_id": "case_demo",
            "launcher": "launcher_simulation",
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
    (case_dir / "config_modflownwt.toml").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "validation_cases.shared.runtime.load_case_metadata",
        lambda _case_dir: {
            "case_id": "case_demo",
            "launcher": "launcher_simulation",
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
