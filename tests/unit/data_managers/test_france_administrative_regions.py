from __future__ import annotations

import pytest

from hydromodpy.data.common.administrative.france import (
    find_departments_in_regions,
    french_region_code,
    known_french_region_names,
    normalize_french_region_key,
    validate_french_regions,
)


@pytest.mark.fast
def test_known_french_regions_include_metropole_and_drom():
    names = set(known_french_region_names())

    assert "Auvergne-Rhone-Alpes" in names
    assert "Bretagne" in names
    assert "Ile-de-France" in names
    assert "Guadeloupe" in names
    assert "La-Reunion" in names
    assert "Mayotte" in names


@pytest.mark.fast
def test_french_region_aliases_are_normalized_to_canonical_labels():
    assert normalize_french_region_key("La Reunion") == "la-reunion"
    assert french_region_code("Auvergne-Rhone-Alpes") == "84"
    assert french_region_code("La Reunion") == "04"
    assert french_region_code("Reunion") == "04"
    assert validate_french_regions(["La Reunion", "84"]) == [
        "La-Reunion",
        "Auvergne-Rhone-Alpes",
    ]


@pytest.mark.fast
def test_unknown_french_region_lists_allowed_names():
    with pytest.raises(ValueError, match="Known regions:"):
        french_region_code("Bretange")


@pytest.mark.fast
def test_find_departments_in_drom_region_code():
    assert find_departments_in_regions(["04"]) == ["974"]
