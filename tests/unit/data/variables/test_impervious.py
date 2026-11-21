"""The sealed share sources: WorldCover tiles of 3 degrees, OCS GE editions by department.

A WorldCover tile is named by its south-west corner, such as N48W003 for 48 to 51 N
and 3 to 0 W. An OCS GE request reads the latest edition of each department up to
the year the section writes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.data.common.clients.ocsge import edition
from hydromodpy.data.variables.impervious.config import ImperviousConfig
from hydromodpy.data.variables.impervious.worldcover import tile_names, tile_url

TILES = [
    pytest.param((-1.3, 48.2, -1.1, 48.5), ["N48W003"], id="the Nancon"),
    pytest.param((-0.5, 46.5, 0.5, 47.5), ["N45W003", "N45E000"], id="across the meridian"),
    pytest.param((-1.0, 50.5, -0.5, 51.5), ["N48W003", "N51W003"], id="across 51 N"),
    pytest.param((-60.5, -3.5, -60.0, -3.0), ["S06W063"], id="south and west"),
]


@pytest.mark.parametrize(("bbox", "names"), TILES)
def test_tile_names(bbox, names):
    assert tile_names(bbox) == names


def test_tile_url_follows_the_algorithm_version_of_the_year():
    assert "/v100/2020/" in tile_url("N48W003", 2020)
    assert tile_url("N48W003", 2021).endswith("ESA_WorldCover_10m_2021_v200_N48W003_Map.tif")


LISTING = """<feed>
<title>OCS-GE_2-0__GPKG_LAMB93_D035_2017-01-01</title>
<title>OCS-GE_2-0__GPKG_LAMB93_D035_2020-01-01</title>
<title>OCS-GE_2-0__GPKG_LAMB93_D035_2023-01-01</title>
<title>OCS-GE_2-0_DIFF-2017-2020_GPKG_LAMB93_D035_2026-03-02</title>
</feed>"""


class Listing:
    def get(self, url):
        return SimpleNamespace(text=LISTING)


EDITIONS = [
    pytest.param(2023, "OCS-GE_2-0__GPKG_LAMB93_D035_2023-01-01", id="the year itself"),
    pytest.param(2022, "OCS-GE_2-0__GPKG_LAMB93_D035_2020-01-01", id="latest before"),
    pytest.param(2030, "OCS-GE_2-0__GPKG_LAMB93_D035_2023-01-01", id="later year"),
    pytest.param(None, "OCS-GE_2-0__GPKG_LAMB93_D035_2023-01-01", id="no year, the latest"),
]


@pytest.mark.parametrize(("year", "name"), EDITIONS)
def test_the_edition_read_is_the_latest_up_to_the_year(year, name):
    assert edition("035", year, Listing()) == name


def test_a_year_before_every_edition_is_refused_with_the_editions():
    with pytest.raises(DataProductError, match=r"serves \[2017, 2020, 2023\]"):
        edition("035", 2015, Listing())


def test_ocsge_needs_its_year_written():
    with pytest.raises(ValidationError, match="year"):
        ImperviousConfig.model_validate({"sources": [{"source": "ocsge"}]})
