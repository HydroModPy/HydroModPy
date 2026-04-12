from __future__ import annotations

from pathlib import Path

from launchers.data_overview.config import DataOverviewConfig


def test_data_overview_config_respects_project_root_env_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.write_text("dummy", encoding="utf-8")
    redirected_project_root = tmp_path / "redirected_project_root"
    monkeypatch.setenv(
        "HYDROMODPY_PROJECT_ROOT",
        str(redirected_project_root),
    )

    cfg = DataOverviewConfig.from_toml(
        {
            "workspace": {
                "project_root": ".",
            },
            "geographic": {
                "catch_def": "from_outlet_coord",
                "dem_init_path": "dem.tif",
                "x_outlet": 1.0,
                "y_outlet": 2.0,
                "snap_dist": "150 m",
                "buff_area": "20%",
            },
        },
        base_dir=tmp_path,
    )

    assert cfg.workspace.project_root == redirected_project_root.resolve()
    assert cfg.geographic.dem_init_path == dem_path.resolve()
