"""The loader holds one store on the data folder of the run, and that store has no database."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.data.loading.loader import DataLoader
from hydromodpy.data.loading.plan import DataLoadPlan


def _loader(tmp_path: Path) -> DataLoader:
    return DataLoader(config_path=tmp_path / "project.toml", data_plan=DataLoadPlan())


def _paths(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(root=tmp_path / "ws", data_dir=tmp_path / "ws" / "data")


def test_the_store_is_made_once(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    loader._init_store(_paths(tmp_path))
    first = loader._require_store()

    loader._init_store(_paths(tmp_path))

    assert loader._require_store() is first


def test_a_run_leaves_no_database_in_the_data_folder(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    paths = _paths(tmp_path)

    loader._init_store(paths)
    loader._require_store().index.rows()

    assert list(paths.data_dir.iterdir()) == []
