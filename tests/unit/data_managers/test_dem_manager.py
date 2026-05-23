from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.variables.dem.config import DemConfig, DemSourceConfig
from hydromodpy.data.variables.dem.manager import DemManager


@pytest.mark.fast
def test_ign_bdalti_explicit_departments_keep_nested_cache_entries(tmp_path, monkeypatch):
    catalog = DataCatalogDuckDB(tmp_path / "cache.duckdb")
    data_dir = tmp_path / "dem"
    fetched: list[Path] = []

    def fake_fetch_bdalti(*, output_dir, bbox, department_codes=None):
        assert department_codes == ["22"]
        path = Path(output_dir) / f"dem_{len(fetched)}.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"bbox={bbox}", encoding="utf-8")
        fetched.append(path)
        return path

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_bdalti.fetch_bdalti",
        fake_fetch_bdalti,
    )
    config = DemConfig(
        sources=[
            DemSourceConfig(
                source="ign_bdalti",
                extent="study_area",
                departments=["22"],
            )
        ]
    )

    small = DemManager(
        config=config,
        catalog=catalog,
        project_extent=(0.0, 0.0, 10.0, 10.0),
        data_dir=data_dir,
    ).load()
    large = DemManager(
        config=config,
        catalog=catalog,
        project_extent=(-5.0, -5.0, 20.0, 20.0),
        data_dir=data_dir,
    ).load()

    small_path = Path(small.fields[0].data)
    large_path = Path(large.fields[0].data)
    assert small_path.exists()
    assert large_path.exists()
    assert small_path != large_path


@pytest.mark.fast
def test_ign_bdalti_regions_resolve_departments(tmp_path, monkeypatch):
    catalog = DataCatalogDuckDB(tmp_path / "cache.duckdb")
    data_dir = tmp_path / "dem"
    captured: dict[str, object] = {}

    def fake_fetch_bdalti(*, output_dir, bbox, department_codes=None):
        captured["department_codes"] = department_codes
        path = Path(output_dir) / "dem_aura.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"bbox={bbox}", encoding="utf-8")
        return path

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_bdalti.fetch_bdalti",
        fake_fetch_bdalti,
    )
    config = DemConfig(
        sources=[
            DemSourceConfig(
                source="ign_bdalti",
                extent="study_area",
                regions=["Auvergne-Rhone-Alpes"],
            )
        ]
    )

    result = DemManager(
        config=config,
        catalog=catalog,
        project_extent=(650000.0, 6400000.0, 1050000.0, 6650000.0),
        data_dir=data_dir,
    ).load()

    assert Path(result.fields[0].data).exists()
    assert captured["department_codes"] == [
        "001",
        "003",
        "007",
        "015",
        "026",
        "038",
        "042",
        "043",
        "063",
        "069",
        "073",
        "074",
    ]
