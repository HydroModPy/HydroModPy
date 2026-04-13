from __future__ import annotations

from pathlib import Path

from hydromodpy.analysis.calibration.engine.session import resolve_workspace_config


def test_model_calibration_runtime_respects_project_root_env_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    redirected_project_root = tmp_path / "redirected_project_root"
    monkeypatch.setenv(
        "HYDROMODPY_PROJECT_ROOT",
        str(redirected_project_root),
    )

    workspace_cfg = resolve_workspace_config(
        {"workspace": {"project_root": "."}},
        simulation_config_path=tmp_path / "calibration.toml",
    )

    assert workspace_cfg.project_root == redirected_project_root.resolve()
