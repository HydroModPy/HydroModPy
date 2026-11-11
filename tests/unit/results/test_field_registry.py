"""Tests for the canonical CF-1.11 field registry (phase G05)."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import UnknownFieldError
from hydromodpy.results import field_registry
from hydromodpy.results.field_registry import (
    FACE_FLOW,
    FIELD_REGISTRY,
    SHAPE_CONNECTION_PAIR,
    SHAPE_TIME,
    SHAPE_TIME_CONNECTION,
    TIME_SERIES_REGISTRY,
    FieldDescriptor,
    TimeSeriesDescriptor,
    all_names,
    all_zarr_paths,
    cf_attrs,
    get,
    has,
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

    def test_is_frozen(self):
        desc = get("head")
        with pytest.raises((AttributeError, Exception)):
            desc.public_name = "other"  # type: ignore[misc]

    def test_coordinates_is_derived_from_shape(self):
        head = get("head")
        assert head.shape == field_registry.SHAPE_TIME_LAYER_FACE
        assert head.coordinates == "time layer face"

        wt = get("watertable_depth")
        assert wt.shape == field_registry.SHAPE_TIME_FACE
        assert wt.coordinates == "time face"


class TestConnectionFields:
    def test_the_face_flow_is_a_series_on_the_connection_axis(self):
        desc = get(FACE_FLOW)
        assert desc.shape == SHAPE_TIME_CONNECTION
        assert desc.zarr_path == FACE_FLOW
        assert desc.dimensions == ("time", "connection")
        assert desc.units == "m3 s-1"
        assert desc.cell_methods == "time: mean"
        assert desc.derived_by == "solver"

    def test_the_connection_cells_pair_two_flat_indices_per_connection(self):
        desc = get("connection_cells")
        assert desc.shape == SHAPE_CONNECTION_PAIR
        assert desc.dimensions == ("connection", "two")
        assert desc.units == "1"
        assert "the smaller first" in desc.long_name
        assert desc.derived_by == "solver"

    def test_a_connection_is_not_a_ugrid_face(self):
        assert SHAPE_TIME_CONNECTION not in field_registry._FACE_SHAPES
        assert SHAPE_CONNECTION_PAIR not in field_registry._FACE_SHAPES
        assert "connection" not in get("head").coordinates.split()
        assert FACE_FLOW in all_names()


class TestPublicAPI:
    def test_get_unknown_raises_unknownfielderror_with_available_names(self):
        with pytest.raises(UnknownFieldError) as exc_info:
            get("unknown_field_xyz")
        err = exc_info.value
        assert err.name == "unknown_field_xyz"
        assert "head" in err.available
        assert "not registered" in err.message

    def test_storage_change_is_refused_with_the_terms_of_the_storage(self):
        # No solver writes it: the storage is read as its budget terms.
        with pytest.raises(UnknownFieldError) as exc_info:
            get("storage_change")
        assert {"storage", "storage_ss", "storage_sy"} <= set(exc_info.value.available)
        assert "storage_ss" in exc_info.value.message

    def test_has(self):
        assert has("head") is True
        assert has("definitely_not_a_field") is False

    def test_all_names_is_sorted(self):
        names = all_names()
        assert names == sorted(names)
        assert "head" in names

    def test_all_zarr_paths_is_sorted(self):
        paths = all_zarr_paths()
        assert paths == sorted(paths)

    def test_cf_attrs_returns_expected_keys(self):
        """``head`` carries a CSDMS fallback (no CF v85 entry for groundwater head)."""
        attrs = cf_attrs("head")
        expected = {
            "csdms_standard_name",
            "long_name",
            "units",
            "cell_methods",
            "grid_mapping",
            "coordinates",
            "mesh",
            "location",
        }
        assert set(attrs) == expected
        assert "standard_name" not in attrs, "no CF v85 entry for groundwater head"
        assert attrs["csdms_standard_name"] == "subsurface_water__hydraulic_head"
        assert attrs["units"] == "m"
        assert attrs["grid_mapping"] == "crs"
        assert attrs["mesh"] == "mesh/topology"
        assert attrs["location"] == "face"

    def test_cf_attrs_emits_standard_name_for_cf_v85_entries(self):
        """``topography`` keeps its CF v85 ``surface_altitude`` standard_name."""
        attrs = cf_attrs("topography")
        assert attrs.get("standard_name") == "surface_altitude"
        assert attrs.get("csdms_standard_name") == "land_surface__elevation"


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
