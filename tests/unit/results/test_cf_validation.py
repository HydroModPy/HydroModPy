"""The bundled CF v85 standard-name list, a frozen set of names a variable may carry."""

from __future__ import annotations

import pytest

from hydromodpy.results.zarr_store.cf_validation import _cf_v85_names, is_cf_standard_name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "groundwater_head_above_reference_level",
        "depth_of_water_table_below_ground_surface",
        "water_table_altitude",
        "specific_yield",
        "specific_storage_coefficient",
        "tendency_of_groundwater_storage_content",
        "totally_invented_concept",
    ],
)
def test_non_cf_names_are_rejected(name: str) -> None:
    assert is_cf_standard_name(name) is False


def test_names_are_a_frozenset() -> None:
    names = _cf_v85_names()
    assert isinstance(names, frozenset)
    assert "surface_altitude" in names
    with pytest.raises(AttributeError):
        names.add("malicious_addition")  # type: ignore[attr-defined]
