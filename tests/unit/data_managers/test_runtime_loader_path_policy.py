from __future__ import annotations

from pathlib import Path

from hydromodpy.data.loader import DataManagersRuntimeLoader
from hydromodpy.data.plan import DataLoadPlan


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
