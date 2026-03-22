from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from launchers.mesh_catchment.batch import (
    MeshCatchmentBatchConfig,
    MeshCatchmentBatchRunner,
)
from launchers.mesh_catchment.config import MeshCatchmentConfigSchema


def test_mesh_catchment_batch_config_from_mapping_returns_typed_values(
    tmp_path: Path,
) -> None:
    batch_cfg = MeshCatchmentBatchConfig.from_mapping(
        {
            "enabled": True,
            "outlets_table_path": "outlets.csv",
            "selection_mode": "selected",
            "selected_outlet_ids": [2, "A3"],
            "outputs": {
                "mesh_filename": "mesh_{outlet_id}.msh",
                "summary_filename": "summary_{outlet_id}.json",
            },
        },
        base_dir=tmp_path,
    )

    assert batch_cfg is not None
    assert batch_cfg.outlets_table_path == (tmp_path / "outlets.csv").resolve()
    assert batch_cfg.selection_mode == "selected"
    assert batch_cfg.selected_outlet_ids == ("2", "A3")
    assert batch_cfg.outputs.mesh_filename == "mesh_{outlet_id}.msh"
    assert batch_cfg.outputs.summary_filename == "summary_{outlet_id}.json"


def test_batch_runner_validate_output_configuration_requires_per_outlet_pattern(
    tmp_path: Path,
) -> None:
    mesh_section_data = MeshCatchmentConfigSchema.model_validate(
        {
            "constraints_mode": "rivers_only",
            "output_figure": "outputs/fixed.png",
        }
    )
    batch_cfg = MeshCatchmentBatchConfig.from_mapping(
        {
            "enabled": True,
            "outlets_table_path": "outlets.csv",
        },
        base_dir=tmp_path,
    )
    assert batch_cfg is not None

    runner = MeshCatchmentBatchRunner(
        config_path=tmp_path / "config.toml",
        mesh_section_data=mesh_section_data,
        workspace_cfg=SimpleNamespace(project_root=tmp_path / "mesh_batch"),
        geographic_cfg=SimpleNamespace(dem_init_path=tmp_path / "dem.tif"),
        domain_cfg=None,
        run_single_workflow=lambda **kwargs: {},
    )

    with pytest.raises(ValueError, match="mesh_catchment_batch.outputs.figure_filename"):
        runner.validate_output_configuration(batch_cfg)
