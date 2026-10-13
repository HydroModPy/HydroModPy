"""A capped breach leaves the cache of the other methods alone and records what it dug."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.spatial.geographic.core.catchment_domain import CatchmentDomainProducts
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths
from hydromodpy.spatial.geographic.pipeline import (
    _geographic_cache_fingerprint,
    _load_cached_geographic_products,
    _raster_products_from_paths,
    _required_geographic_cache_artifacts,
    _write_geographic_cache_manifest,
)
from hydromodpy.spatial.geographic.store_ingestion import _ingest_metadata
from hydromodpy.spatial.terrain import CappedBreach, CappedBreachReport
from tests._helpers.terrain_doubles import fake_flow_products
from tests.unit.geographic.test_geographic_cache import _touch_artifact

FILL_FINGERPRINT_WITHOUT_THE_BURN = (
    "7b2ef36222c1439414f36aa3464a7c51e18ed18111f14601fb4112f79344a363"
)
"""The fingerprint of 79fe734ea, before the capped breach existed, minus the burn.

Removing ``[geographic.enforce_streams]`` took its section and its path signature out of
the payload, so every cached tree is rebuilt once. Putting both back (defaults, no path)
gives back ``ab83e008ba427355b3c68345745088b13a0337e006164879216e8d7571f626b3``, the value
a clean export of 79fe734ea computes: the capped breach key is the only other thing the
payload could have gained, and it is absent.

The DEM is a bare file name that does not exist. The payload holds the path as the OS
spells it, so a name without a separator is the one input that hashes alike everywhere.
"""

REPORT = CappedBreachReport(
    cells_lowered=4,
    cells_raised=12,
    max_lowering_m=0.56,
    max_raise_m=0.2,
    max_dist_cells=8,
    max_cost_m=0.5,
    move_threshold_m=0.01,
)


def _config(method: str, **overrides) -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=1.0, y=2.0, dem="no_such_dem.tif", dem_correc_type=method, **overrides
    )


def test_a_fill_config_fingerprints_as_before_the_capped_breach_existed(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert _geographic_cache_fingerprint(_config("fill")) == FILL_FINGERPRINT_WITHOUT_THE_BURN


def test_the_breach_key_is_absent_from_the_payload_unless_it_is_set() -> None:
    assert _geographic_cache_fingerprint(_config("breach")) != _geographic_cache_fingerprint(
        _config("fill")
    )
    capped = _geographic_cache_fingerprint(_config("capped_breach"))
    other = _geographic_cache_fingerprint(
        _config("capped_breach", capped_breach={"max_depth": 0.8, "max_distance": 100.0})
    )
    assert capped != other


def _written_cache(tmp_path: Path):
    dem = tmp_path / "dem.tif"
    dem.write_text("dem", encoding="utf-8")
    config = GeographicConfig.model_validate(
        {
            "catchment": {
                "catch_def": "from_outlet_coord",
                "dem_init_path": str(dem),
                "x_outlet": 1.0,
                "y_outlet": 2.0,
                "snap_dist": 10.0,
                "buff_area": 10.0,
            },
            "dem_correc_type": "capped_breach",
            "reuse_existing_outputs": True,
        }
    )
    paths = build_geographic_paths(tmp_path / "project")
    for path in _required_geographic_cache_artifacts(
        config=config, paths=paths, raster_products=_raster_products_from_paths(paths)
    ):
        _touch_artifact(path)
    flow_products = fake_flow_products(method=CappedBreach(0.5, 200.0))
    conditioned = replace(
        flow_products.accumulation.directions.conditioned_dem, breach_report=REPORT
    )
    directions = replace(flow_products.accumulation.directions, conditioned_dem=conditioned)
    flow_products = type(flow_products)(
        accumulation=replace(flow_products.accumulation, directions=directions)
    )
    _write_geographic_cache_manifest(
        config=config,
        paths=paths,
        domain_products=CatchmentDomainProducts(
            catchment_area_km2=12.0,
            buffer_distance_m=300.0,
            watershed_buff_shp=str(Path(paths.geographic_path) / "watershed_buff.shp"),
            watershed_box_shp=paths.watershed_box_shp,
            watershed_box_buff_shp=paths.box_buff,
        ),
        catchment_area_km2=12.0,
        catchment_products=None,
        flow_products=flow_products,
    )
    return config, paths, flow_products


def test_the_description_keeps_the_report_and_a_cache_hit_reads_it_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config, paths, _written = _written_cache(tmp_path)

    with caplog.at_level(logging.INFO):
        cached = _load_cached_geographic_products(
            config=config, paths=paths, crs_project="EPSG:2154"
        )

    assert cached is not None
    assert cached.flow_products.accumulation.directions.conditioned_dem.breach_report == REPORT
    assert any("realised max lowering 0.560 m" in record.getMessage() for record in caplog.records)


def test_the_run_metadata_records_the_limits_and_what_they_produced(tmp_path: Path) -> None:
    _config_, _paths, flow_products = _written_cache(tmp_path)
    written: dict[str, str] = {}
    store = SimpleNamespace(write_geographic_metadata=lambda _sim, meta: written.update(meta))
    geographic = SimpleNamespace(
        dem_correc_type="capped_breach",
        capped_breach=None,
        _flow_products=flow_products,
    )

    _ingest_metadata(geographic, store, "sim")

    assert written["capped_breach_max_depth_m"] == "0.5"
    assert written["capped_breach_realised_max_lowering_m"] == "0.56"
    assert written["capped_breach_realised_cells_raised"] == "12"


def test_a_fill_run_records_no_report() -> None:
    written: dict[str, str] = {}
    store = SimpleNamespace(write_geographic_metadata=lambda _sim, meta: written.update(meta))
    geographic = SimpleNamespace(
        dem_correc_type="fill", capped_breach=None, _flow_products=fake_flow_products()
    )

    _ingest_metadata(geographic, store, "sim")

    assert not [key for key in written if key.startswith("capped_breach")]
