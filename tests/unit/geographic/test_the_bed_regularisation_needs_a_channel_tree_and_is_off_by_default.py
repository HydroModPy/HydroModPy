"""``[geographic.bed_regularization]`` ships off, needs a channel tree, and signs the cache only when on."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.pipeline import _geographic_cache_fingerprint

_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}


def _outlet(**sections) -> GeographicConfig:
    return GeographicConfig.from_outlet(x=0.0, y=0.0, dem="dem.tif", **sections)


def test_the_section_is_off_with_the_sfr_default_slope() -> None:
    section = _outlet().bed_regularization

    assert section.enabled is False
    assert section.min_slope == pytest.approx(1.0e-4)


def test_it_is_refused_without_the_river_network() -> None:
    with pytest.raises(ValidationError, match=r"needs\s+\[geographic.river_network\]"):
        _outlet(bed_regularization={"enabled": True})


def test_it_is_refused_on_a_dem_domain() -> None:
    with pytest.raises(ValidationError, match="catch_def = dem"):
        GeographicConfig.from_dem(
            "dem.tif", river_network=_RIVER, bed_regularization={"enabled": True}
        )


def test_a_negative_slope_is_refused() -> None:
    with pytest.raises(ValidationError):
        _outlet(river_network=_RIVER, bed_regularization={"enabled": True, "min_slope": -1e-4})


def test_off_it_leaves_a_cached_tree_valid_and_on_it_does_not() -> None:
    plain = _geographic_cache_fingerprint(_outlet(river_network=_RIVER))
    off = _geographic_cache_fingerprint(
        _outlet(river_network=_RIVER, bed_regularization={"enabled": False, "min_slope": 1e-3})
    )
    on = _geographic_cache_fingerprint(
        _outlet(river_network=_RIVER, bed_regularization={"enabled": True})
    )

    assert off == plain
    assert on != plain
