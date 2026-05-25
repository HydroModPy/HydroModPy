from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.variables.dem.config import (
    DemConfig,
    IgnBdaltiDemSource,
    IgnGeoplateformeDemSource,
)
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
            IgnBdaltiDemSource(
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
            IgnBdaltiDemSource(
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


@pytest.mark.fast
def test_ign_geoplateforme_dem_regions_dispatch_to_dynamic_client(tmp_path, monkeypatch):
    catalog = DataCatalogDuckDB(tmp_path / "cache.duckdb")
    data_dir = tmp_path / "dem"
    captured: dict[str, object] = {}

    def fake_fetch_ign_dem(
        *,
        output_dir,
        bbox,
        departments=None,
        dataset,
        resolution_m,
        file_format,
        crs,
        force_refresh,
    ):
        captured.update(
            {
                "output_dir": output_dir,
                "bbox": bbox,
                "departments": departments,
                "dataset": dataset,
                "resolution_m": resolution_m,
                "file_format": file_format,
                "crs": crs,
                "force_refresh": force_refresh,
            }
        )
        path = Path(output_dir) / "processed" / "dem_dynamic.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dynamic", encoding="utf-8")
        return path

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem",
        fake_fetch_ign_dem,
    )
    config = DemConfig(
        sources=[
            IgnGeoplateformeDemSource(
                extent="study_area",
                regions=["Auvergne-Rhone-Alpes"],
                dataset="bd-alti",
                resolution_m=25.0,
                file_format="ASC",
                crs="epsg:2154",
                force_refresh=True,
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
    assert result.fields[0].source == "ign_geoplateforme_dem"
    assert captured["dataset"] == "bd-alti"
    assert captured["resolution_m"] == 25.0
    assert captured["file_format"] == "ASC"
    assert captured["crs"] == "epsg:2154"
    assert captured["force_refresh"] is True
    assert captured["departments"] == [
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
    source_unit, fetch_metadata = catalog.connection.execute(
        """
        SELECT source_unit, fetch_metadata
        FROM entries
        WHERE variable = 'dem' AND source = 'ign_geoplateforme_dem'
        """
    ).fetchone()
    assert source_unit == "bd-alti:25m:ASC"
    metadata = json.loads(fetch_metadata)
    assert metadata["provider"] == "ign_geoplateforme"
    assert metadata["dataset"] == "bd-alti"
    assert metadata["resolution_m"] == 25.0
    assert metadata["departments"] == captured["departments"]
