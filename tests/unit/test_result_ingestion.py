from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

from hydromodpy.workflow.steps.result_ingestion import step_save_run_artifacts


def test_step_save_run_artifacts_writes_config_snapshot(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)

    ctx = SimpleNamespace(
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root), run_id="run"),
        raw_toml={
            "workspace": {"root": str(project_root)},
            "simulation": {"run_id": "snapshot_case"},
        },
        cfg=SimpleNamespace(capability_gallery=SimpleNamespace(enabled=False)),
        execution=SimpleNamespace(simulation_plan=SimpleNamespace(runs=[])),
        store=None,
        sim_id=None,
    )

    step_save_run_artifacts(ctx, wall_seconds=0.1)

    snapshot_path = project_root / "_config_snapshot.toml"
    assert snapshot_path.is_file()
    payload = tomllib.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["simulation"]["run_id"] == "snapshot_case"
