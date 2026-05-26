from __future__ import annotations

import os

import pytest

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.variables.dem.apis.ign_dem_fr import (
    discover_ign_dem_files,
    download_ign_dem_departments,
)
from hydromodpy.data.variables.dem.config import DemConfig, IgnGeoplateformeDemSource
from hydromodpy.data.variables.dem.manager import DemManager

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.getenv("HMP_RUN_IGN_NETWORK_TESTS") != "1",
        reason="Set HMP_RUN_IGN_NETWORK_TESTS=1 to run IGN Geoplateforme network tests.",
    ),
]


def test_geoplateforme_bd_alti_discovery_dry_run_for_finistere(tmp_path):
    files = discover_ign_dem_files(
        departments=["29"],
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        timeout=30.0,
        allow_static_bdalti_fallback=False,
    )
    if not files:
        pytest.skip(
            "IGN Geoplateforme dynamic discovery returned no BD ALTI file for D029; "
            "the production path may still use the static BD ALTI fallback."
        )

    assert files[0].department == "D029"
    assert "25M" in files[0].file_name.upper()
    assert files[0].url.startswith("https://")

    paths = download_ign_dem_departments(
        output_dir=tmp_path,
        departments=["29"],
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        dry_run=True,
        max_files=1,
        timeout=30.0,
    )

    assert len(paths) == 1
    assert paths[0].parent.name == "D029"
    assert paths[0].suffix.lower() == ".7z"


@pytest.mark.skipif(
    os.getenv("HMP_RUN_IGN_DOWNLOAD_TESTS") != "1",
    reason="Set HMP_RUN_IGN_DOWNLOAD_TESTS=1 to download a real IGN archive.",
)
def test_geoplateforme_bd_alti_download_one_archive_for_finistere(tmp_path):
    paths = download_ign_dem_departments(
        output_dir=tmp_path,
        departments=["29"],
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        dry_run=False,
        max_files=1,
        timeout=120.0,
        requests_per_second=2.0,
    )

    assert len(paths) == 1
    assert paths[0].is_file()
    assert paths[0].stat().st_size > 0


@pytest.mark.skipif(
    os.getenv("HMP_RUN_IGN_ASSEMBLY_TESTS") != "1",
    reason=(
        "Set HMP_RUN_IGN_ASSEMBLY_TESTS=1 to run a real DemManager "
        "download/extract/merge/crop check."
    ),
)
def test_geoplateforme_dem_manager_bd_alti_assembly_for_small_finistere_bbox(tmp_path):
    catalog = DataCatalogDuckDB(tmp_path / "cache.duckdb")
    config = DemConfig(
        sources=[
            IgnGeoplateformeDemSource(
                extent="study_area",
                departments=["29"],
                dataset="bd-alti",
                resolution_m=25.0,
                file_format="ASC",
            )
        ]
    )

    result = DemManager(
        config=config,
        catalog=catalog,
        project_extent=(145000.0, 6820000.0, 147000.0, 6822000.0),
        data_dir=tmp_path / "dem",
    ).load()

    assert len(result.fields) == 1
    assert result.fields[0].source == "ign_geoplateforme_dem"
    assert result.fields[0].data.is_file()
    assert result.fields[0].data.name.startswith("dem_ign_geoplateforme_bdalti_25m_")
