"""Toggling ``[geographic.snap_streams]`` keeps the geographic cache.

The snap moves the mapped network onto the model graph after the run. It
changes no geographic product, so a cache written with it off is reused with it
on, and the reverse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.spatial.geographic.core.catchment_domain import CatchmentDomainProducts
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths
from hydromodpy.spatial.geographic.pipeline import (
    _geographic_cache_fingerprint,
    _load_cached_geographic_products,
    _raster_products_from_paths,
    _required_geographic_cache_artifacts,
    _write_geographic_cache_manifest,
)
from tests.unit.geographic.test_geographic_cache import _cached_config, _touch_artifact

SNAP_SETTINGS = (
    {"mode": "off"},
    {"mode": "diagnose"},
    {"mode": "apply", "radius": "150 m"},
)


def _with_snap(config, settings: dict):
    snap = config.snap_streams.model_validate(settings)
    return config.model_copy(update={"snap_streams": snap})


@pytest.mark.parametrize("settings", SNAP_SETTINGS[1:])
def test_the_snap_leaves_the_fingerprint_unchanged(tmp_path: Path, settings: dict) -> None:
    config = _cached_config(tmp_path)

    assert _geographic_cache_fingerprint(_with_snap(config, settings)) == (
        _geographic_cache_fingerprint(config)
    )


def test_a_cache_written_without_the_snap_is_reused_with_it(tmp_path: Path) -> None:
    config = _cached_config(tmp_path)
    paths = build_geographic_paths(tmp_path / "project")
    for path in _required_geographic_cache_artifacts(
        config=config,
        paths=paths,
        raster_products=_raster_products_from_paths(paths),
    ):
        _touch_artifact(path)
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
    )

    for settings in SNAP_SETTINGS:
        cached = _load_cached_geographic_products(
            config=_with_snap(config, settings),
            paths=paths,
            crs_project="EPSG:2154",
        )
        assert cached is not None, settings
