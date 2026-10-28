"""``[geographic.crossings]`` follows the generated channel tree, so it refuses what has none."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers.geographic_cases import BENCH_RIVER


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


def test_the_notch_is_accepted_with_a_river_network_and_its_lengths_take_units() -> None:
    assert _outlet(crossings={"enabled": True}, river_network=BENCH_RIVER).crossings.enabled
    assert _outlet(crossings={"enabled": False}).crossings.enabled is False
    notch = _outlet(
        crossings={"notch_width": "20 m", "bed_reach": "0.1 km", "max_depth": "2 m"}
    ).crossings
    assert (notch.notch_width, notch.bed_reach, notch.max_depth) == (20.0, 100.0, 2.0)


_ON = {"crossings": {"enabled": True}, "river_network": BENCH_RIVER}


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: _outlet(crossings={"enabled": True}), "river_network"),
        (lambda: GeographicConfig.from_dem("dem.tif", **_ON), "catch_def"),
        (lambda: GeographicConfig.synthetic_case(**_ON), "synthetic"),
        (lambda: _outlet(crossings={"kinds": ["weir"]}), "kinds"),
        (lambda: _outlet(crossings={"depth": 3.0}), "Extra inputs"),
        (lambda: _outlet(crossings={"max_depth": 0.0}), "max_depth"),
        (lambda: _outlet(reg_fold="regional_job", **_ON), "reg_fold"),
    ],
    ids=[
        "without-a-river-network",
        "on-a-direct-dem-domain",
        "on-a-synthetic-support",
        "a-weir-is-not-a-kind-to-notch",
        "an-unknown-key",
        "a-limit-must-be-positive",
        "a-corrected-ground-cannot-share-a-regional-flow-routed-on-the-raw-dem",
    ],
)
def test_a_notch_with_no_channel_tree_to_follow_is_refused(build, match) -> None:
    with pytest.raises(ValidationError, match=match):
        build()
