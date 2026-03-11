from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from validation_cases.shared.runtime import run_launcher_validation_case


def test_run_launcher_validation_case_keeps_outputs_when_launcher_exits_nonzero(
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
        "validation_cases.shared.runtime.run_example_script",
        lambda **kwargs: SimpleNamespace(
            returncode=1,
            stdout="partial run",
            stderr="solver did not converge",
        ),
    )
    model_ws = tmp_path / "outputs" / "watershed" / "results_simulations" / "model"
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    monkeypatch.setattr(
        "validation_cases.shared.runtime.resolve_model_workspace",
        lambda *args, **kwargs: (model_ws, postprocess_dir, particles_dir),
    )

    result = run_launcher_validation_case(case_dir=case_dir, test_file=__file__)

    assert result.model_ws == model_ws
    assert result.run_returncode == 1
    assert result.run_stdout == "partial run"
    assert result.run_stderr == "solver did not converge"


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
        "validation_cases.shared.runtime.run_example_script",
        lambda **kwargs: SimpleNamespace(
            returncode=1,
            stdout="partial run",
            stderr="solver did not converge",
        ),
    )
    monkeypatch.setattr(
        "validation_cases.shared.runtime.resolve_model_workspace",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Model folder not found")),
    )

    with pytest.raises(AssertionError, match="launcher_simulation.py failed"):
        run_launcher_validation_case(case_dir=case_dir, test_file=__file__)
