from __future__ import annotations

import os

import pytest

from hydromodpy.data.variables.dem.apis.ign_dem_fr import (
    discover_ign_dem_files,
    download_ign_dem_departments,
)

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
