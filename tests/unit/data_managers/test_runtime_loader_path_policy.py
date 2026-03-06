from __future__ import annotations

from pathlib import Path

from hydromodpy.data_managers.plan import DataLoadPlan
from hydromodpy.data_managers.runtime_loader import DataManagersRuntimeLoader
from hydromodpy.simulation.workspace import WorkspacePathRegistry


def _build_loader(tmp_path: Path) -> DataManagersRuntimeLoader:
    return DataManagersRuntimeLoader(
        config_path=tmp_path / "launcher.toml",
        data_plan=DataLoadPlan(),
    )


def test_resolve_manager_input_path_uses_section_override(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path)
    resolved = loader._resolve_manager_input_path(
        section={"hydro_path": "inputs/hydrography"},
        keys=("hydro_path",),
        default_root=tmp_path / "data",
    )
    assert resolved == (tmp_path / "inputs" / "hydrography").resolve()


def test_resolve_manager_input_path_falls_back_to_workspace_data(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path)
    default_root = tmp_path / "data"
    resolved = loader._resolve_manager_input_path(
        section={},
        keys=("hydro_path",),
        default_root=default_root,
    )
    assert resolved == default_root


def test_station_output_legacy_default_is_redirected_to_workspace(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path)
    workspace_paths = WorkspacePathRegistry(
        catch_name="demo",
        out_dir_path=tmp_path / "out",
        data_path=tmp_path / "data",
    )
    payload = {
        "source": {},
        "selection": {},
        "output": {"path": "hydromodpy/data_managers/hydrometry/exports"},
    }

    loader._resolve_station_set_paths(
        payload,
        manager_type="hydrometry",
        workspace_paths=workspace_paths,
    )

    assert Path(payload["output"]["path"]) == workspace_paths.manager_stable_folder("hydrometry")


def test_station_output_explicit_relative_path_stays_user_controlled(tmp_path: Path) -> None:
    loader = _build_loader(tmp_path)
    workspace_paths = WorkspacePathRegistry(
        catch_name="demo",
        out_dir_path=tmp_path / "out",
        data_path=tmp_path / "data",
    )
    payload = {
        "source": {"local_data_dir": "raw/hydrometry"},
        "selection": {"mask_path": "masks/watershed.shp"},
        "output": {"path": "exports/custom_hydrometry"},
    }

    loader._resolve_station_set_paths(
        payload,
        manager_type="hydrometry",
        workspace_paths=workspace_paths,
    )

    assert Path(payload["source"]["local_data_dir"]) == (tmp_path / "raw" / "hydrometry").resolve()
    assert Path(payload["selection"]["mask_path"]) == (tmp_path / "masks" / "watershed.shp").resolve()
    assert Path(payload["output"]["path"]) == (tmp_path / "exports" / "custom_hydrometry").resolve()
