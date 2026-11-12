"""Tests for the canonical CF-1.11 field registry (phase G05)."""

from __future__ import annotations

import pytest

from hydromodpy.results import field_registry
from hydromodpy.results.field_registry import (
    FIELD_REGISTRY,
    SHAPE_TIME,
    TIME_SERIES_REGISTRY,
    FieldDescriptor,
    TimeSeriesDescriptor,
    all_zarr_paths,
    series_names,
    series_unit,
)
from hydromodpy.results.zarr_store.cf_validation import is_cf_standard_name


class TestRegistryContents:
    def test_has_eighteen_fields(self):
        assert len(FIELD_REGISTRY) >= 18

    def test_registry_exposes_essential_public_names(self):
        # Hard-required set from the G05 plan.
        required = {
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
        assert required <= set(FIELD_REGISTRY)

    def test_public_name_matches_key(self):
        for key, desc in FIELD_REGISTRY.items():
            assert desc.public_name == key, f"Public name mismatch for {key}: {desc.public_name!r}"

    def test_zarr_paths_are_unique(self):
        paths = [d.zarr_path for d in FIELD_REGISTRY.values()]
        assert len(paths) == len(set(paths)), "duplicate zarr_path detected"

    def test_cf_metadata_is_non_empty(self):
        """Every entry has long_name + units; a semantic name comes from either CF or CSDMS.

        V1 sets ``standard_name`` to an empty string when the hydrogeology
        concept has no CF v85 entry; in that case the CSDMS fallback
        (``csdms_standard_name``) must be present instead.
        """
        for name, desc in FIELD_REGISTRY.items():
            assert desc.long_name, f"{name} missing long_name"
            assert desc.units, f"{name} missing units"
            assert desc.standard_name or desc.csdms_standard_name, (
                f"{name} missing both standard_name and csdms_standard_name"
            )


class TestFieldDescriptor:
    def test_every_budget_flux_states_the_one_sign(self):
        for desc in field_registry.FIELD_REGISTRY.values():
            if desc.zarr_path.startswith("budget/") and desc.public_name not in (
                field_registry.NOT_AQUIFER_TERMS
            ):
                assert "aquifer" in desc.long_name, desc.public_name
                assert "positive leaves" not in desc.long_name, desc.public_name
                attrs = field_registry.cf_attrs(desc.public_name)
                assert attrs["sign_convention"] == field_registry.BUDGET_SIGN_RULE

    def test_the_cf_names_of_the_registry_are_in_the_bundled_table(self):
        named = {
            desc.standard_name
            for desc in field_registry.FIELD_REGISTRY.values()
            if desc.standard_name
        }
        assert named == {"altitude", "cell_thickness", "surface_altitude", "water_table_depth"}
        assert all(is_cf_standard_name(name) for name in named)


class TestPublicAPI:
    def test_all_zarr_paths_is_sorted(self):
        paths = all_zarr_paths()
        assert paths == sorted(paths)


_RATES = (
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


class TestSeriesRegistry:
    def test_shape_time_is_the_shape_of_a_station_series(self):
        assert SHAPE_TIME == "time"

    def test_the_catchment_series_are_registered_with_their_units(self):
        registry = TIME_SERIES_REGISTRY
        assert registry["discharge"].units == "m3 s-1"
        assert registry["well_pumping"].units == "m3 s-1"
        assert registry["reservoir_storage"].units == "m"

    def test_the_lake_and_reach_states_are_registered(self):
        registry = TIME_SERIES_REGISTRY
        assert registry["stage"].units == "m"
        assert registry["volume"].units == "m3"
        assert registry["surface_area"].units == "m2"
        assert registry["depth"].units == "m"

    @pytest.mark.parametrize("name", _RATES)
    def test_a_rate_of_a_lake_or_reach_is_a_flow(self, name):
        assert TIME_SERIES_REGISTRY[name].units == "m3 s-1"

    def test_storage_is_not_a_series_name(self):
        # A lake's storage and the budget field storage of the aquifer are two
        # volumes of control, so the lake writes its term as lake_storage.
        assert "storage" not in TIME_SERIES_REGISTRY
        assert "lake_storage" in TIME_SERIES_REGISTRY

    def test_every_series_names_itself(self):
        for name, descriptor in TIME_SERIES_REGISTRY.items():
            assert descriptor.public_name == name
            assert descriptor.long_name

    def test_a_time_descriptor_has_no_zarr_dimensions(self):
        for descriptor in TIME_SERIES_REGISTRY.values():
            assert not hasattr(descriptor, "dimensions")
            assert not hasattr(descriptor, "zarr_path")

    def test_series_and_field_tables_are_disjoint(self):
        assert not set(TIME_SERIES_REGISTRY) & set(FIELD_REGISTRY)

    def test_series_unit_of_an_unregistered_name_is_empty(self):
        assert series_unit("unknown") == ""

    def test_all_series_names_are_sorted(self):
        assert series_names() == sorted(series_names())
