"""A soil parameter outside its physical range is refused with its own message.

Each bound is written in a ``field_validator`` with a clean text (F1 to F7),
not by Pydantic's ``ge``/``le``, which would raise its generic message first.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig

_CASES = [
    (
        "ru",
        -1.0,
        "ru = -1 mm is outside 0 to 1000 mm, the range of a soil water capacity: "
        'ru is in mm, so write ru = 120 or ru = "120 mm".',
    ),
    (
        "ru",
        1001.0,
        "ru = 1001 mm is outside 0 to 1000 mm, the range of a soil water capacity: "
        'ru is in mm, so write ru = 120 or ru = "120 mm".',
    ),
    (
        "alpha",
        0.0,
        "alpha = 0: alpha is the share of ru above which the soil evaporates at the "
        "full rate kc x ETP, above 0 and at most 1. Write a value such as 0.6.",
    ),
    (
        "alpha",
        1.5,
        "alpha = 1.5: alpha is the share of ru above which the soil evaporates at "
        "the full rate kc x ETP, above 0 and at most 1. Write a value such as 0.6.",
    ),
    (
        "kc",
        -0.1,
        "kc = -0.1: kc scales the loaded ETP, between 0 and 2. Write 1.0 to take "
        "the ETP as loaded.",
    ),
    (
        "kc",
        2.1,
        "kc = 2.1: kc scales the loaded ETP, between 0 and 2. Write 1.0 to take the ETP as loaded.",
    ),
    (
        "impervious_fraction",
        -0.1,
        "impervious_fraction = -0.1: it is the sealed share of the area, a fraction "
        "from 0 up to, not including, 1: write 0.05 for 5 %, not 5, and 0.0 for a "
        "rural catchment.",
    ),
    (
        "impervious_fraction",
        1.0,
        "impervious_fraction = 1: it is the sealed share of the area, a fraction "
        "from 0 up to, not including, 1: write 0.05 for 5 %, not 5, and 0.0 for a "
        "rural catchment.",
    ),
    (
        "bypass_fraction",
        -0.1,
        "bypass_fraction = -0.1: it is the share of the rain that skips the soil, "
        "a fraction from 0 up to, not including, 1: write 0.1 for 10 %, not 10, "
        "and 0.0 unless the site shows preferential flow.",
    ),
    (
        "bypass_fraction",
        1.0,
        "bypass_fraction = 1: it is the share of the rain that skips the soil, a "
        "fraction from 0 up to, not including, 1: write 0.1 for 10 %, not 10, and "
        "0.0 unless the site shows preferential flow.",
    ),
    (
        "transit_time",
        -1.0,
        "transit_time = -1 days is outside 0 to 30 days: a longer delay would "
        "rebuild the slow groundwater memory MODFLOW computes itself. Write 0 to "
        "send the recharge the same day, or a few days.",
    ),
    (
        "transit_time",
        31.0,
        "transit_time = 31 days is outside 0 to 30 days: a longer delay would "
        "rebuild the slow groundwater memory MODFLOW computes itself. Write 0 to "
        "send the recharge the same day, or a few days.",
    ),
]


@pytest.mark.parametrize(("field", "value", "text"), _CASES)
def test_a_parameter_outside_its_range_is_refused_by_name(
    field: str, value: float, text: str
) -> None:
    with pytest.raises(ValidationError, match=re.escape(text)):
        SoilReservoirConfig(**{"ru": 100.0, field: value})


def test_an_unknown_spinup_word_gets_its_own_message() -> None:
    text = (
        "spinup = 'permanent': write \"first_year\" to repeat the first year of the "
        'run until the soil storage settles, or "none" to start from a full soil.'
    )
    with pytest.raises(ValidationError, match=re.escape(text)):
        SoilReservoirConfig(ru=100.0, spinup="permanent")
