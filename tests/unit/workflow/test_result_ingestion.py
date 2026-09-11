from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.workflow.steps.export import step_save_run_artifacts


def test_step_save_run_artifacts_does_not_write_config_snapshot_sidecars(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)

    ctx = SimpleNamespace(
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root), run_id="run"),
        raw_toml={
            "workspace": {"root": str(project_root)},
            "simulation": {"run_id": "snapshot_case"},
        },
        cfg=SimpleNamespace(
            analysis=SimpleNamespace(capability_gallery=SimpleNamespace(enabled=False))
        ),
        execution=SimpleNamespace(simulation_plan=SimpleNamespace(runs=[])),
        store=None,
        sim_id=None,
    )

    step_save_run_artifacts(ctx, wall_seconds=0.1)

    assert not (project_root / "_config_snapshot.toml").exists()
    assert not (project_root / "_config_snapshot.json").exists()
