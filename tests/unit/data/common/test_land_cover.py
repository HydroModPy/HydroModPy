"""The land cover pivot: the GCN250 rows, and the crosswalks of each legend to ESA CCI.

GCN250 (Jaafar et al. 2019) gives each CCI class the curve numbers of its plant functional
types weighed by their shares. Recomputing a few rows from Table 1 and the shares of the
online-only Table 1 guards the transcribed numbers; a share of .5 rounds either way, so
the check holds to one curve number.
"""

from __future__ import annotations

import pytest

from hydromodpy.data.common.land_cover import (
    CCI_CLASSES,
    CLC_TO_CCI,
    CROSSWALKS,
    LEFT_OUT,
    OCSGE_TO_CCI,
    WORLDCOVER_TO_CCI,
    curve_number,
    pivot_of,
)

# Table 1 of Jaafar et al. (2019): curve numbers of each plant functional type, A to D.
PFT = {
    "tree_br_ev": (30, 55, 70, 77),
    "tree_br_de": (33, 58, 72, 78),
    "tree_ne_ev": (33, 58, 72, 78),
    "tree_ne_de": (45, 66, 77, 83),
    "shrub_br_ev": (40, 58, 72, 79),
    "shrub_br_de": (42, 62, 75, 81),
    "shrub_ne_ev": (42, 62, 75, 81),
    "natural_grass": (39, 61, 74, 80),
    "managed_grass": (57, 68, 75, 78),
    "bare": (77, 86, 91, 94),
    "water": (100, 100, 100, 100),
}

# Shares, in %, of the online-only Table 1 for a few classes.
SHARES = {
    30: {"tree_br_ev": 5, "tree_br_de": 5, "shrub_br_ev": 5, "shrub_br_de": 5,
         "shrub_ne_ev": 5, "natural_grass": 15, "managed_grass": 60},
    60: {"tree_br_de": 70, "shrub_br_de": 15, "natural_grass": 15},
    100: {"tree_br_ev": 10, "tree_br_de": 20, "tree_ne_ev": 5, "tree_ne_de": 5,
          "shrub_br_ev": 5, "shrub_br_de": 10, "shrub_ne_ev": 5, "natural_grass": 40},
    130: {"natural_grass": 60, "bare": 40},
    190: {"tree_br_de": 2.5, "tree_ne_ev": 2.5, "natural_grass": 15, "bare": 75, "water": 5},
}  # fmt: skip


@pytest.mark.parametrize("cci", sorted(SHARES))
def test_a_row_is_the_mean_of_its_plant_types(cci):
    shares = SHARES[cci]
    assert sum(shares.values()) == pytest.approx(100.0)
    for column in range(4):
        mean = sum(share * PFT[pft][column] for pft, share in shares.items()) / 100.0
        assert abs(CCI_CLASSES[cci].curve_numbers[column] - mean) <= 1.0


def test_every_crosswalk_points_to_a_class_of_the_pivot():
    for name, crosswalk in CROSSWALKS.items():
        assert all(v == LEFT_OUT or v in CCI_CLASSES for v in crosswalk.values()), name
    assert len(CLC_TO_CCI) == 44
    assert len(WORLDCOVER_TO_CCI) == 11


SEALED = [
    pytest.param("ocsge", "CS1.1.1.1", id="OCS GE built"),
    pytest.param("ocsge", "CS1.1.1.2", id="OCS GE roads"),
    pytest.param("worldcover", "50", id="WorldCover built-up"),
    pytest.param("clc", "112", id="CLC discontinuous urban fabric"),
    pytest.param("clc", "122", id="CLC road and rail"),
    pytest.param("cci", "190", id="CCI urban"),
]


@pytest.mark.parametrize(("legend", "code"), SEALED)
def test_a_sealed_class_is_left_to_the_sealed_share(legend, code):
    assert pivot_of(code, CROSSWALKS[legend]) == LEFT_OUT


def test_a_meadow_reads_the_managed_grass_row_and_not_grassland():
    # GCN250 grassland (130) holds 40 % bare soil and runs off more than a field on B to D.
    assert pivot_of("CS2.2.1", OCSGE_TO_CCI) == 11
    assert pivot_of("231", CLC_TO_CCI) == 11
    assert curve_number(11, 2) == 75 < curve_number(130, 2) == 81


def test_the_longest_ocsge_key_wins_and_numeric_codes_match_whole():
    assert pivot_of("CS2.1.1.3", OCSGE_TO_CCI) == 90
    assert pivot_of("CS9", OCSGE_TO_CCI) is None
    assert pivot_of("21", CLC_TO_CCI) is None


def test_water_and_snow_have_no_curve_number():
    assert curve_number(210, 0) is None
    assert curve_number(220, 3) is None
    assert curve_number(11, 3) == 78
