from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.data.loader import DataManagersRuntimeLoader
from hydromodpy.data.plan import DataLoadPlan


def _build_loader(tmp_path: Path) -> DataManagersRuntimeLoader:
    return DataManagersRuntimeLoader(
        config_path=tmp_path / "launcher.toml",
        data_plan=DataLoadPlan(explicit_types=("oceanic",)),
    )


def test_load_generic_oceanic_variable_passes_geographic_to_manager(
    monkeypatch,
    tmp_path: Path,
) -> None:
    loader = _build_loader(tmp_path)
    geographic = SimpleNamespace(watershed_shp=tmp_path / "watershed.shp")
    captured: dict[str, object] = {}
    load_result = object()

    class FakeConfig:
        def __init__(self) -> None:
            self.date_start = "2003-01-01"
            self.date_end = "2003-01-30"
            self.sources = [SimpleNamespace(source="shom", mask_path=None)]

        @classmethod
        def model_validate(cls, _payload):
            return cls()

    class FakeManager:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def load(self):
            return load_result

    def fake_import_module(name: str):
        if name == "hydromodpy.data.variables.oceanic.config":
            return SimpleNamespace(OceanicConfig=FakeConfig)
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr("hydromodpy.data.loader.importlib.import_module", fake_import_module)
    monkeypatch.setattr("hydromodpy.data.store.get_manager_class", lambda variable: FakeManager)

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

    assert captured["geographic"] is geographic
    assert result.loaded_data.oceanic is load_result
