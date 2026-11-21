"""The infiltration ratio from OCS GE: one ratio per cover, the sealed covers left nodata.

The archives are replaced by a few cover polygons, so each test reads the 10 m map
the source burns. A key starts a cover code, and the longest one wins.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from shapely.geometry import box

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.data.variables.infiltration_ratio import ocsge
from hydromodpy.data.variables.infiltration_ratio.config import InfiltrationRatioConfig

BBOX = (0.0, 0.0, 40.0, 10.0)


@pytest.fixture
def four_covers(monkeypatch, tmp_path):
    """Four 10 m squares side by side: built, wood, grass and water."""
    covers = gpd.GeoDataFrame(
        {"code_cs": ["CS1.1.1.1", "CS2.1.1.1", "CS2.2.1", "CS1.2.2"]},
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10), box(20, 0, 30, 10), box(30, 0, 40, 10)],
        crs="EPSG:2154",
    )
    monkeypatch.setattr(
        ocsge, "department_archives", lambda **kw: ([tmp_path / "D035.7z"], ["D035"])
    )
    monkeypatch.setattr(ocsge, "cover_polygons", lambda archive, bbox: covers)
    return tmp_path


def burned(folder, ratios):
    path = ocsge.fetch_ocsge_infiltration_ratio(
        output_dir=folder, bbox=BBOX, year=2023, ratios=ratios
    )
    with rasterio.open(path) as raster:
        return raster.read(1)[0].tolist(), raster.nodata


def test_each_cover_takes_the_longest_key_and_the_sealed_cover_stays_nodata(four_covers):
    row, nodata = burned(four_covers, {"CS2": 0.5, "CS2.1": 0.8, "CS": 0.3})

    assert nodata == -1.0
    assert row == pytest.approx([-1.0, 0.8, 0.5, 0.3])


def test_a_cover_no_key_starts_is_refused_with_its_share(four_covers):
    with pytest.raises(DataProductError, match=r"CS1\.2\.2 \(33\.3 %\)"):
        burned(four_covers, {"CS2": 0.5})


REFUSALS = [
    pytest.param({"CS1.1.1.2": 0.1}, "hold only the sealed covers", id="a sealed cover"),
    pytest.param({"CLC231": 0.6}, "start no OCS GE cover code", id="not a cover code"),
    pytest.param({"CS2": 1.2}, "leave 0 to 1", id="above one"),
]


@pytest.mark.parametrize(("ratios", "match"), REFUSALS)
def test_the_table_of_ratios_is_refused_when_it_cannot_hold(ratios, match):
    with pytest.raises(ValidationError, match=match):
        InfiltrationRatioConfig.model_validate(
            {"sources": [{"source": "ocsge", "year": 2023, "ratios": ratios}]}
        )


def test_the_source_needs_its_year_and_its_table():
    with pytest.raises(ValidationError, match="ratios"):
        InfiltrationRatioConfig.model_validate({"sources": [{"source": "ocsge", "year": 2023}]})
    with pytest.raises(ValidationError, match="year"):
        InfiltrationRatioConfig.model_validate(
            {"sources": [{"source": "ocsge", "ratios": {"CS": 1}}]}
        )


def test_ratio_of_reads_no_key_as_none():
    assert ocsge.ratio_of("CS2.1.1.1", {"CS2.2": 0.4}) is None
    assert np.isclose(ocsge.ratio_of("CS2.1.1.1", {"CS": 0.4, "CS2.1.1.1": 0.9}), 0.9)
