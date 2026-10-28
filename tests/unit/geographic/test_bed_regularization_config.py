"""``[geographic.bed_regularization]`` ships off with the SFR slope and needs a channel tree."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers.geographic_cases import BENCH_RIVER


def _outlet(**sections) -> GeographicConfig:
    return GeographicConfig.from_outlet(x=0.0, y=0.0, dem="dem.tif", **sections)


def test_the_section_is_off_with_the_sfr_default_slope() -> None:
    section = _outlet().bed_regularization

    assert section.enabled is False
    assert section.min_slope == pytest.approx(1.0e-4)


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (
            lambda: _outlet(bed_regularization={"enabled": True}),
            r"needs\s+\[geographic.river_network\]",
        ),
        (
            lambda: GeographicConfig.from_dem(
                "dem.tif", river_network=BENCH_RIVER, bed_regularization={"enabled": True}
            ),
            "catch_def = dem",
        ),
        (
            lambda: _outlet(
                river_network=BENCH_RIVER,
                bed_regularization={"enabled": True, "min_slope": -1e-4},
            ),
            "min_slope",
        ),
    ],
    ids=["without-the-river-network", "on-a-dem-domain", "a-negative-slope"],
)
def test_a_bed_regularisation_with_no_channel_tree_or_slope_is_refused(build, match) -> None:
    with pytest.raises(ValidationError, match=match):
        build()
