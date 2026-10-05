"""A cached geographic tree stays valid for a project that does not use the notch."""

from __future__ import annotations

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.pipeline import _geographic_cache_fingerprint

_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}


def _config(**crossings) -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=1.0, y=2.0, dem="dem.tif", river_network=_RIVER, crossings=crossings
    )


def test_a_limit_of_a_notch_that_is_off_does_not_invalidate_the_cache() -> None:
    assert _geographic_cache_fingerprint(_config(max_depth=2.0)) == _geographic_cache_fingerprint(
        _config()
    )


def test_a_limit_of_a_notch_that_is_on_does() -> None:
    first = _config(enabled=True, max_depth=2.0)
    second = _config(enabled=True, max_depth=2.5)

    assert _geographic_cache_fingerprint(first) != _geographic_cache_fingerprint(second)


def test_switching_the_notch_on_changes_the_fingerprint() -> None:
    assert _geographic_cache_fingerprint(_config()) != _geographic_cache_fingerprint(
        _config(enabled=True)
    )


def test_editing_the_structures_file_in_place_changes_the_fingerprint(tmp_path) -> None:
    structures = tmp_path / "crossings.gpkg"
    structures.write_bytes(b"one")
    config = _config(enabled=True, path=structures)
    before = _geographic_cache_fingerprint(config)

    structures.write_bytes(b"two, longer")

    assert _geographic_cache_fingerprint(config) != before
