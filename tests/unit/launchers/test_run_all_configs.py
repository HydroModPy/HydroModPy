from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_run_all_configs_module():
    module_path = Path("launchers/mesh_catchment/run_all_configs.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "test_run_all_configs_module",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_step_plan_collocates_identification_and_mesh_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_run_all_configs_module()

    results_root = tmp_path / "results"
    monkeypatch.setenv("HYDROMODPY_RESULTS_ROOT", str(results_root))

    mesh_config_dir = tmp_path / "mesh_configs"
    identification_dir = tmp_path / "ident_configs"
    mesh_config_dir.mkdir()
    identification_dir.mkdir()

    dem_path = tmp_path / "data" / "dem.tif"
    dem_path.parent.mkdir(parents=True, exist_ok=True)
    dem_path.write_text("dummy", encoding="utf-8")

    mesh_config_path = mesh_config_dir / "config_demo_case.toml"
    mesh_config_path.write_text(
        "\n".join(
            [
                "[workspace]",
                'project_root = "~/HydroModPy/original_mesh_root"',
                "",
                "[mesh_catchment]",
                'constraints_mode = "rivers_only"',
                "",
                "[mesh_catchment_batch]",
                "enabled = true",
                'outlets_table_path = "stale/outlets.csv"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    identification_config_path = identification_dir / "config_demo_case.toml"
    identification_config_path.write_text(
        "\n".join(
            [
                "[catchment_identification_scan]",
                f'dem_path = "{dem_path.as_posix()}"',
                'output_dir = "~/HydroModPy/original_identification_root"',
                'outlets_csv_name = "selected_demo_outlets.csv"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    plan = module._build_step_plan(
        step={
            "mesh_config": mesh_config_path.name,
            "identification_config": identification_config_path.name,
        },
        mesh_config_dir=mesh_config_dir,
        identification_dir=identification_dir,
    )

    scenario_root = results_root / "mesh_catchment_runs" / "demo_case"
    identification_dir_out = scenario_root / "identification"
    mesh_dir_out = scenario_root / "mesh"

    assert plan.scenario_name == "demo_case"
    assert plan.scenario_root == scenario_root.resolve()
    assert plan.identification_command is not None
    assert len(plan.cleanup_paths) == 2

    identification_override_path = Path(
        plan.identification_command[plan.identification_command.index("--config") + 1]
    )
    mesh_override_path = Path(plan.mesh_command[-1])

    try:
        identification_override_text = identification_override_path.read_text(
            encoding="utf-8"
        )
        mesh_override_text = mesh_override_path.read_text(encoding="utf-8")

        assert identification_override_path.parent == identification_dir
        assert mesh_override_path.parent == mesh_config_dir
        assert 'base_config = "config_demo_case.toml"' in identification_override_text
        assert "\n\n" not in identification_override_text
        assert f'output_dir = "{identification_dir_out.as_posix()}"' in identification_override_text
        assert (
            f'"{(identification_dir_out / "selected_demo_outlets.csv").as_posix()}"'
            in mesh_override_text
        )
        assert "\n\n" not in mesh_override_text
        assert f'project_root = "{mesh_dir_out.as_posix()}"' in mesh_override_text
    finally:
        for path in plan.cleanup_paths:
            path.unlink(missing_ok=True)


def test_cleanup_stale_override_configs_removes_previous_temp_files(
    tmp_path: Path,
) -> None:
    module = _load_run_all_configs_module()

    mesh_dir = tmp_path / "mesh"
    ident_dir = tmp_path / "ident"
    mesh_dir.mkdir()
    ident_dir.mkdir()
    stale_mesh = mesh_dir / "._run_all_demo_mesh_deadbeef.toml"
    stale_ident = ident_dir / "._run_all_demo_ident_deadbeef.toml"
    untouched = mesh_dir / "config_demo_case.toml"
    stale_mesh.write_text("mesh", encoding="utf-8")
    stale_ident.write_text("ident", encoding="utf-8")
    untouched.write_text("keep", encoding="utf-8")

    deleted = module._cleanup_stale_override_configs(mesh_dir, ident_dir)

    assert stale_mesh.resolve() in deleted
    assert stale_ident.resolve() in deleted
    assert not stale_mesh.exists()
    assert not stale_ident.exists()
    assert untouched.exists()
