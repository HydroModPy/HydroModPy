"""The canonical CF field registry and the registry of station series, with their units."""

from __future__ import annotations

import pytest

from hydromodpy.results import field_registry
from hydromodpy.results.field_registry import (
    FIELD_REGISTRY,
    SHAPE_TIME,
    TIME_SERIES_REGISTRY,
    all_zarr_paths,
    series_names,
    series_unit,
)
from hydromodpy.results.zarr_store.cf_validation import is_cf_standard_name

REQUIRED_FIELDS = {
    "head",
    "concentration",
    "watertable_elevation",
    "watertable_depth",
    "seepage_mask",
    "storage",
    "storage_ss",
    "storage_sy",
    "recharge",
    "drain",
    "outflow_drain",
    "release_flux",
    "drain_accumulation_flux",
    "release_accumulation_flux",
    "river",
    "well",
    "topography",
    "layer_thickness",
    "hydraulic_conductivity",
    "specific_yield",
    "specific_storage",
    "porosity",
}

RATES = (
    "gwf_exchange",
    "lake_bed_vertical_exchange",
    "rainfall",
    "evaporation",
    "runoff",
    "inflow",
    "withdrawal",
    "ext_outflow",
    "outlet",
    "outlet_inflow",
    "to_mvr",
    "from_mvr",
    "lak_connection",
    "lake_storage",
    "cutoff_wall_flow",
    "downstream_flow",
    "ext_inflow",
    "gw_exchange",
)

SERIES_UNITS = [
    pytest.param("discharge", "m3 s-1", id="discharge"),
    pytest.param("well_pumping", "m3 s-1", id="well pumping"),
    pytest.param("reservoir_storage", "m", id="reservoir storage"),
    pytest.param("stage", "m", id="stage"),
    pytest.param("volume", "m3", id="volume"),
    pytest.param("surface_area", "m2", id="surface area"),
    pytest.param("depth", "m", id="depth"),
    *[pytest.param(name, "m3 s-1", id=f"rate {name}") for name in RATES],
]


def test_registry_holds_the_public_names():
    assert len(FIELD_REGISTRY) >= 18
    assert REQUIRED_FIELDS <= set(FIELD_REGISTRY)


def test_public_name_matches_key():
    for key, desc in FIELD_REGISTRY.items():
        assert desc.public_name == key, f"Public name mismatch for {key}: {desc.public_name!r}"


def test_zarr_paths_are_unique():
    paths = [d.zarr_path for d in FIELD_REGISTRY.values()]
    assert len(paths) == len(set(paths)), "duplicate zarr_path detected"


def test_cf_metadata_is_non_empty():
    # A field with no CF entry has an empty standard_name and a CSDMS name instead.
    for name, desc in FIELD_REGISTRY.items():
        assert desc.long_name, f"{name} missing long_name"
        assert desc.units, f"{name} missing units"
        assert desc.standard_name or desc.csdms_standard_name, (
            f"{name} missing both standard_name and csdms_standard_name"
        )


def test_budget_flux_states_the_one_sign():
    for desc in FIELD_REGISTRY.values():
        if desc.zarr_path.startswith("budget/") and desc.public_name not in (
            field_registry.NOT_AQUIFER_TERMS
        ):
            assert "aquifer" in desc.long_name, desc.public_name
            assert "positive leaves" not in desc.long_name, desc.public_name
            attrs = field_registry.cf_attrs(desc.public_name)
            assert attrs["sign_convention"] == field_registry.BUDGET_SIGN_RULE


def test_cf_names_are_in_the_bundled_table():
    named = {desc.standard_name for desc in FIELD_REGISTRY.values() if desc.standard_name}

    assert named == {"altitude", "cell_thickness", "surface_altitude", "water_table_depth"}
    assert all(is_cf_standard_name(name) for name in named)


def test_all_zarr_paths_is_sorted():
    paths = all_zarr_paths()

    assert paths == sorted(paths)


def test_shape_time_is_the_station_series_shape():
    assert SHAPE_TIME == "time"


@pytest.mark.parametrize(("name", "units"), SERIES_UNITS)
def test_series_units(name, units):
    assert TIME_SERIES_REGISTRY[name].units == units


def test_storage_is_not_a_series_name():
    # A lake's storage and the budget field storage of the aquifer are two
    # volumes of control, so the lake writes its term as lake_storage.
    assert "storage" not in TIME_SERIES_REGISTRY
    assert "lake_storage" in TIME_SERIES_REGISTRY


def test_every_series_names_itself():
    for name, descriptor in TIME_SERIES_REGISTRY.items():
        assert descriptor.public_name == name
        assert descriptor.long_name


def test_series_have_no_zarr_dimensions():
    for descriptor in TIME_SERIES_REGISTRY.values():
        assert not hasattr(descriptor, "dimensions")
        assert not hasattr(descriptor, "zarr_path")


def test_series_and_field_tables_are_disjoint():
    assert not set(TIME_SERIES_REGISTRY) & set(FIELD_REGISTRY)


def test_series_unit_of_an_unknown_name_is_empty():
    assert series_unit("unknown") == ""


def test_series_names_are_sorted():
    assert series_names() == sorted(series_names())
