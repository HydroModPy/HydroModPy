"""One spelling for the units of a stored table, whatever wrote them."""

from __future__ import annotations

import pytest

from hydromodpy.core.units.udunits import udunits_spelling


@pytest.mark.parametrize(
    ("written", "spelled"),
    [
        ("m3/s", "m3 s-1"),
        ("m3 s-1", "m3 s-1"),
        ("m^3/s", "m3 s-1"),
        ("m**3/s", "m3 s-1"),
        ("m3/d", "m3 d-1"),
        ("m3/day", "m3 d-1"),
        ("mm/day", "mm d-1"),
        ("mm/d", "mm d-1"),
        ("m/s", "m s-1"),
        ("m/d", "m d-1"),
        ("kg/s", "kg s-1"),
        ("kg/m3", "kg m-3"),
        ("1/m", "m-1"),
        ("m-1", "m-1"),
        ("1/s", "s-1"),
        ("-", "1"),
        ("1", "1"),
        ("dimensionless", "1"),
        ("%", "percent"),
        ("D", "d"),
        ("day", "d"),
        ("d", "d"),
        ("m", "m"),
        ("mg/L", "mg L-1"),
        ("mg/l", "mg L-1"),
        ("MJ/m2/j", "MJ m-2 d-1"),
        ("°C", "degC"),
        ("", ""),
        (None, ""),
    ],
)
def test_a_unit_is_written_one_way(written: str | None, spelled: str) -> None:
    assert udunits_spelling(written) == spelled


def test_a_text_the_grammar_cannot_read_stays_as_the_provider_wrote_it() -> None:
    assert udunits_spelling("mg(NO3)/L") == "mg(NO3)/L"
