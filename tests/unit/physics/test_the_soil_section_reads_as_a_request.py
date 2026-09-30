"""The soil section reads a hydrogeologist's request, not a Pydantic internal.

``ru`` and ``transit_time`` carry their own unit, so a file writes ``"120 mm"``
or ``"5 days"`` and the section reads the same value as a bare number in the
canonical unit. ``ru`` has no default: it belongs to the site, so a file that
omits it is refused rather than started from a silent guess.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig


def test_ru_reads_a_bare_number_and_a_string_in_millimetres() -> None:
    assert SoilReservoirConfig(ru=120).ru == pytest.approx(120.0)
    assert SoilReservoirConfig(ru="120 mm").ru == pytest.approx(120.0)
    assert SoilReservoirConfig(ru="12 cm").ru == pytest.approx(120.0)


def test_transit_time_reads_a_string_in_days() -> None:
    config = SoilReservoirConfig(ru=100.0, transit_time="5 days")

    assert config.transit_time == pytest.approx(5.0)


def test_the_defaults_describe_a_passive_soil() -> None:
    config = SoilReservoirConfig(ru=100.0)

    assert config.alpha == pytest.approx(0.6)
    assert config.kc == pytest.approx(1.0)
    assert config.impervious_fraction == pytest.approx(0.0)
    assert config.bypass_fraction == pytest.approx(0.0)
    assert config.transit_time == pytest.approx(0.0)
    assert config.spinup == "first_year"


def test_ru_is_required() -> None:
    with pytest.raises(ValidationError):
        SoilReservoirConfig()
