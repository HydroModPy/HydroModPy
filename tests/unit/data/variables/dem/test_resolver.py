"""The DEM resolver seals the source with the state its row declares."""

from __future__ import annotations

import numpy as np

from hydromodpy.data.variables.dem.resolver import resolve_dem
from tests._helpers.geotiffs import write_geotiff


def _cfg(path, *, state: str | None = None) -> dict:
    source = {"source": "file", "path": str(path)}
    if state is not None:
        source["state"] = state
    return {"data": {"dem": {"sources": [source]}}}


def test_a_file_source_reads_its_declared_state(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", np.ones((4, 4)), cell=25.0, crs="EPSG:2154")

    record = resolve_dem(_cfg(dem, state="conditioned"))

    assert record.state == "conditioned"
    assert record.origin == "file"


def test_a_file_source_defaults_to_raw_when_it_says_none(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", np.ones((4, 4)), cell=25.0, crs="EPSG:2154")

    record = resolve_dem(_cfg(dem))

    assert record.state == "raw"


def test_no_source_at_all_resolves_to_none() -> None:
    assert resolve_dem({"data": {"dem": {"sources": []}}}) is None
