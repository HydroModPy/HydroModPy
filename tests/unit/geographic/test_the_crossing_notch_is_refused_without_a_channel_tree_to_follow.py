"""[geographic.crossings] follows the generated channel tree, so it refuses what has none."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}


def _outlet(**overrides) -> GeographicConfig:
    return GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif", **overrides)


def test_the_notch_is_off_by_default_with_the_documented_limits() -> None:
    notch = _outlet().crossings

    assert notch.enabled is False
    assert notch.path is None
    assert notch.kinds == ["road", "railway", "bridge"]
    assert (notch.notch_width, notch.bed_reach, notch.max_depth, notch.snap_radius) == (
        10.0,
        50.0,
        3.0,
        30.0,
    )


def test_enabled_without_a_river_network_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"river_network"):
        _outlet(crossings={"enabled": True})


def test_enabled_with_a_river_network_is_accepted() -> None:
    config = _outlet(crossings={"enabled": True}, river_network=_RIVER)

    assert config.crossings.enabled is True


def test_a_disabled_notch_accepts_a_disabled_river_network() -> None:
    assert _outlet(crossings={"enabled": False}).crossings.enabled is False


def test_enabled_on_a_direct_dem_domain_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"catch_def"):
        GeographicConfig.from_dem("dem.tif", crossings={"enabled": True}, river_network=_RIVER)


def test_enabled_on_a_synthetic_support_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"synthetic"):
        GeographicConfig.synthetic_case(crossings={"enabled": True}, river_network=_RIVER)


def test_a_weir_is_not_a_kind_to_notch() -> None:
    with pytest.raises(ValidationError):
        _outlet(crossings={"kinds": ["weir"]})


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        _outlet(crossings={"depth": 3.0})


def test_the_lengths_accept_inline_units() -> None:
    notch = _outlet(
        crossings={"notch_width": "20 m", "bed_reach": "0.1 km", "max_depth": "2 m"}
    ).crossings

    assert (notch.notch_width, notch.bed_reach, notch.max_depth) == (20.0, 100.0, 2.0)


def test_a_limit_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _outlet(crossings={"max_depth": 0.0})


@pytest.mark.parametrize("section", ["dam_carve", "crossings"])
def test_a_corrected_ground_cannot_share_a_regional_flow_routed_on_the_raw_dem(section) -> None:
    corrections = {
        "dam_carve": {"dam_carve": {"enabled": True, "line_path": "dam.gpkg"}},
        "crossings": {"crossings": {"enabled": True}, "river_network": _RIVER},
    }[section]

    with pytest.raises(ValidationError, match="reg_fold"):
        _outlet(reg_fold="regional_job", **corrections)


def test_the_description_of_dam_carve_says_it_corrects_the_ground() -> None:
    description = GeographicConfig.model_fields["dam_carve"].description

    assert "ground" in description
    assert "routing chain" in description
