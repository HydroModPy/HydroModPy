"""What the generic load path hands an oceanic manager, now that it is not an object.

The test this replaces asserted the opposite: that ``_load_generic_variable``
passed ``result.setup.geographic`` straight through to the manager. It did,
through a ``**extra_kwargs`` on ``DataStore.load_variable`` that existed for
that one key. The project run still knows where the watershed is -- it fills
``mask_path`` with it, the way it already did for every other timeseries
source -- and the manager reads the file.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.data.loading import loader as loader_module
from hydromodpy.data.loading.loader import DataManagersRuntimeLoader
from hydromodpy.data.managers.plan import DataLoadPlan
from hydromodpy.data.variables.oceanic.config import OceanicConfig


def _build_loader(tmp_path: Path) -> DataManagersRuntimeLoader:
    return DataManagersRuntimeLoader(
        config_path=tmp_path / "launcher.toml",
        data_plan=DataLoadPlan(explicit_types=("oceanic",)),
    )


def _run_generic_oceanic(monkeypatch, tmp_path: Path, captured: dict) -> object:
    loader = _build_loader(tmp_path)
    geographic = SimpleNamespace(watershed_shp=tmp_path / "watershed.shp")
    load_result = object()

    class FakeManager:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def load(self):
            return load_result

    def fake_import_module(name: str):
        if name == "hydromodpy.data.variables.oceanic.config":
            return SimpleNamespace(OceanicConfig=OceanicConfig)
        raise AssertionError(f"Unexpected import: {name}")

    # Rebind the loader module's own importlib name: a dotted target would resolve
    # the stdlib module and mutate it for the whole session.
    monkeypatch.setattr(
        loader_module, "importlib", SimpleNamespace(import_module=fake_import_module)
    )
    monkeypatch.setattr(
        "hydromodpy.data.loading.store.get_manager_class", lambda variable: FakeManager
    )

    result = SimpleNamespace(
        cfg=SimpleNamespace(
            data=SimpleNamespace(
                oceanic={
                    "date_start": "2003-01-01",
                    "date_end": "2003-01-30",
                    "sources": [{"source": "shom"}],
                }
            ),
            overview=None,
        ),
        setup=SimpleNamespace(geographic=geographic),
        loaded_data=SimpleNamespace(),
    )

    loader._load_generic_variable(result, "oceanic")
    return result, load_result, geographic


@pytest.mark.fast
def test_the_generic_path_hands_the_manager_no_project_object(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}
    result, load_result, _ = _run_generic_oceanic(monkeypatch, tmp_path, captured)

    assert "geographic" not in captured, captured
    assert set(captured) == {"config", "catalog", "project_extent", "project_period", "data_dir"}
    assert result.loaded_data.oceanic is load_result


@pytest.mark.fast
def test_the_delineated_watershed_reaches_the_source_as_a_mask(monkeypatch, tmp_path: Path):
    """The seam that replaces the object, on the path a project run takes."""
    captured: dict[str, object] = {}
    _, _, geographic = _run_generic_oceanic(monkeypatch, tmp_path, captured)

    source = captured["config"].sources[0]
    assert source.mask_path == Path(geographic.watershed_shp)
