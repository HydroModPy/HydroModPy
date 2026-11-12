"""One spelling for the units of a stored table, whatever wrote them."""

from __future__ import annotations

import pytest

from hydromodpy.results.storage.udunits import udunits_spelling


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
        ("kg/m2/s", "kg m-2 s-1"),
        ("m3/s/km2", "m3 s-1 km-2"),
        ("uS/cm", "uS cm-1"),
        ("°C", "degC"),
        ("", ""),
        (None, ""),
    ],
)
def test_unit_spelling(written: str | None, spelled: str) -> None:
    assert udunits_spelling(written) == spelled


@pytest.mark.parametrize(
    "written",
    [
        "mg(NO3)/L",
        "mg/L NO3",
        "mg NO3/L",
        "n/a",
        "m a s l",
        "m a.s.l.",
        "m NGF",
        "kg/m2 s",
        "M3/S",
        "/s",
    ],
)
def test_unreadable_text_is_kept(written: str) -> None:
    assert udunits_spelling(written) == written
