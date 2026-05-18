"""Unit tests for the bundled CF v85 standard-name validator."""

from __future__ import annotations

import pytest

from hydromodpy.results.zarr_store.cf_validation import cf_v85_names, is_cf_standard_name


@pytest.mark.parametrize(
    "name",
    [
        "surface_altitude",
        "cell_thickness",
        "land_binary_mask",
        "surface_runoff_flux",
        "water_flux_into_sea_water_from_rivers",
        "soil_porosity",
    ],
)
def test_is_cf_standard_name_recognises_curated_entries(name: str) -> None:
    """Every name in the curated CF v85 list is recognised."""
    assert is_cf_standard_name(name) is True


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
def test_is_cf_standard_name_rejects_non_cf_v85(name: str) -> None:
    """Concepts outside the curated CF v85 list return False."""
    assert is_cf_standard_name(name) is False


def test_cf_v85_names_is_frozenset() -> None:
    """The exposed list is immutable to prevent runtime mutation."""
    names = cf_v85_names()
    assert isinstance(names, frozenset)
    assert "surface_altitude" in names
    with pytest.raises(AttributeError):
        names.add("malicious_addition")  # type: ignore[attr-defined]
