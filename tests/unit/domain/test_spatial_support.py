"""The supports a heterogeneous parameter reads its zones from, and their providers.

The domain grid is 4 x 4 cells of 5 m from (10, 100) to (30, 120), so its
centre is (20, 110) and its largest inscribed circle has a radius of 10 m.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.spatial import CatchmentZonesField
from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.spatial_support import (
    SupportBuildContext,
    build_default_spatial_support_provider_registry,
)
from hydromodpy.spatial.domain.spatial_support_config import (
    CatchmentZonesSupportConfig,
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
    GeologySupportConfig,
)
from hydromodpy.spatial.domain.support_fields import (
    AliasedSpatialSupportField,
    GeneratedRingsSupportField,
    RasterZonesSupportField,
)
from hydromodpy.spatial.surface import Surface
from tests._helpers.domain_cases import raster_support, surface

GRID = {"cell": 5.0, "x0": 10.0, "y0": 100.0}
CODES = np.array([[1, 1, 2, 3], [1, 2, 2, 3], [0, 2, 2, 3], [1, 1, 1, 0]], dtype=np.uint8)
ZONES = {1: "domain", 2: "buffer", 3: "core"}
REGISTRY = build_default_spatial_support_provider_registry()


def _domain() -> Domain:
    return Domain(
        DomainConfig(zone_ids=["catchment"]), surface_topo=surface(np.zeros((4, 4)), **GRID)
    )


def _context(domain: object = None, loaded_data: object = None) -> SupportBuildContext:
    return SupportBuildContext(
        cfg=SimpleNamespace(), raw_toml={}, workspace=None, geographic=None, domain_geographic=None,
        domain=_domain() if domain is None else domain, flow=None, loaded_data=loaded_data, time_grid=None,
    )  # fmt: skip


def _build(
    kind: str,
    config: object,
    context: SupportBuildContext | None = None,
    support_id: str = "support",
):
    return REGISTRY.get(kind).build(support_id=support_id, config=config, context=context or _context())  # fmt: skip


def _catchment_zones() -> CatchmentZonesField:
    return CatchmentZonesField(
        identifier="catchment_zones", encoded_codes=CODES, encoded_to_zone=ZONES
    )


@pytest.mark.parametrize(
    ("config", "breaks", "points", "labels"),
    [
        ({"axis": "x", "breaks": [0.5]}, [20.0], ([12.0, 25.0], [110.0, 110.0]), ["left", "right"]),
        ({"axis": "y", "coordinate_mode": "absolute", "breaks": ["0.105 km"]}, [105.0], ([20.0, 20.0], [101.0, 119.0]), ["left", "right"]),
    ],
    ids=["relative_x", "absolute_y"],
)  # fmt: skip
def test_generated_bands_split_the_domain_along_their_axis(config, breaks, points, labels):
    support = _build("generated_bands", GeneratedBandsSupportConfig(kind="generated_bands", labels=["left", "right"], **config), support_id="halves")  # fmt: skip

    assert support.identifier == "halves"
    assert support.breaks_abs == breaks
    assert support.zone_keys == ("left", "right")
    np.testing.assert_array_equal(support.zone_id(*map(np.array, points)), labels)


@pytest.mark.parametrize(
    ("config", "radii", "points", "labels"),
    [
        ({"radii": [0.5]}, [5.0], ([20.0, 27.0], [110.0, 110.0]), ["inner", "outer"]),
        ({"coordinate_mode": "absolute", "radii": [2.0], "center_x": 15.0, "center_y": "0.112 km"}, [2.0], ([15.0, 20.0], [111.0, 110.0]), ["inner", "outer"]),
    ],
    ids=["relative_around_the_centre", "absolute_around_a_given_point"],
)  # fmt: skip
def test_generated_rings_are_concentric_inside_the_domain(config, radii, points, labels):
    support = _build("generated_rings", GeneratedRingsSupportConfig(kind="generated_rings", labels=["inner", "outer"], **config), support_id="rings")  # fmt: skip

    assert support.identifier == "rings"
    assert (support.radii_abs, support.zone_keys) == (radii, ("inner", "outer"))
    np.testing.assert_array_equal(support.zone_id(*map(np.array, points)), labels)


def test_catchment_zones_wrap_the_catchment_zone_of_the_domain():
    domain = _domain()
    domain.set_zone("catchment", _catchment_zones())

    support = _build("catchment_zones", CatchmentZonesSupportConfig(kind="catchment_zones"), _context(domain), "zones")  # fmt: skip

    assert isinstance(support, RasterZonesSupportField)
    assert (support.identifier, support.zone_keys, support.shape) == (
        "zones",
        ("domain", "buffer", "core"),
        (4, 4),
    )
    x, y = np.array([[12.0, 27.0], [12.0, 40.0]]), np.array([[118.0, 118.0], [107.0, 110.0]])
    np.testing.assert_array_equal(support.zone_id(x, y), [["domain", "core"], ["", ""]])


def test_a_geology_support_is_the_loaded_geology_or_an_alias_of_it():
    geology = SimpleNamespace(identifier="field_geology", zone_keys=["granite", "schist"], default_cell_samples_per_axis=4,
                              on_mesh=lambda mesh, *, cell_samples_per_axis: (mesh, cell_samples_per_axis), units="lithology")  # fmt: skip
    context = _context(loaded_data=SimpleNamespace(geology=geology))
    config = GeologySupportConfig(kind="geology")

    assert _build("geology", config, context, "field_geology") is geology
    alias = _build("geology", config, context, "rocks")

    assert isinstance(alias, AliasedSpatialSupportField)
    assert (alias.identifier, alias.zone_keys, alias.default_cell_samples_per_axis) == (
        "rocks",
        ("granite", "schist"),
        4,
    )
    assert alias.units == "lithology"
    assert alias.on_mesh("mesh", cell_samples_per_axis=3) == ("mesh", 3)


def test_only_the_geology_provider_needs_data_and_runs_in_the_data_phase():
    phases = {kind: (REGISTRY.get(kind).build_phase, REGISTRY.get(kind).required_data_types(None))
              for kind in ("generated_bands", "generated_rings", "catchment_zones", " Geology ")}  # fmt: skip

    assert phases.pop(" Geology ") == ("data", ("geology",))
    assert set(phases.values()) == {("setup", ())}
    with pytest.raises(ValueError, match="Unknown spatial support provider 'voronoi'"):
        REGISTRY.get("voronoi")


_NO_SUPPORT = SimpleNamespace(surface_topo=Surface(name="surface_topo", values=np.zeros((2, 2))), get_zone=lambda _id: _catchment_zones())  # fmt: skip
_BANDS = GeneratedBandsSupportConfig(kind="generated_bands", coordinate_mode="absolute", breaks=[35.0], labels=["a", "b"])  # fmt: skip
_RINGS = GeneratedRingsSupportConfig(kind="generated_rings", coordinate_mode="absolute", radii=[10.0], labels=["a", "b"])  # fmt: skip
_CATCHMENT = CatchmentZonesSupportConfig(kind="catchment_zones")
_GEOLOGY = GeologySupportConfig(kind="geology")


@pytest.mark.parametrize(
    ("kind", "config", "context", "error", "match"),
    [
        ("generated_bands", _BANDS, _context(_NO_SUPPORT), ValueError, "requires domain.surface_topo.support"),
        ("generated_rings", _RINGS, _context(_NO_SUPPORT), ValueError, "requires domain.surface_topo.support"),
        ("catchment_zones", _CATCHMENT, _context(_NO_SUPPORT), ValueError, "requires domain.surface_topo.support"),
        ("generated_bands", _BANDS, None, ValueError, r"strictly inside the domain x extent \(10.0, 30.0\)"),
        ("generated_rings", _RINGS, None, ValueError, "strictly inside the largest inscribed circle"),
        ("generated_rings", _RINGS.model_copy(update={"center_x": 10.0}), None, ValueError, "center must lie strictly inside"),
        ("catchment_zones", _CATCHMENT, None, ValueError, "requires domain zone 'catchment'"),
        ("catchment_zones", _CATCHMENT, _context(SimpleNamespace(get_zone=lambda _id: object())), TypeError, "must expose encoded_codes"),
        ("geology", _GEOLOGY, None, ValueError, "requires loaded geology data"),
        ("geology", _GEOLOGY, _context(loaded_data=SimpleNamespace()), ValueError, "requires loaded geology data"),
    ],
)  # fmt: skip
def test_a_provider_refuses_what_it_cannot_build(kind, config, context, error, match):
    with pytest.raises(error, match=match):
        _build(kind, config, context)


@pytest.mark.parametrize(
    ("change", "error", "match"),
    [
        ({"encoded_codes": CODES[0]}, ValueError, "must be a 2D integer array"),
        ({"encoded_codes": np.zeros((0, 0))}, ValueError, "cannot be empty"),
        ({"encoded_to_zone": {}}, ValueError, "encoded_to_zone cannot be empty"),
        ({"encoded_to_zone": {**ZONES, -1: "deep"}}, ValueError, "must be positive integers"),
        ({"encoded_to_zone": {**ZONES, 3: " "}}, ValueError, "labels cannot be empty"),
        ({"raster_support": "EPSG:2154"}, TypeError, "must be a RasterSupport instance"),
        ({"raster_support": raster_support(4, 3, **GRID)}, ValueError, "shape mismatch"),
        ({"encoded_to_zone": {1: "domain", 2: "buffer"}}, ValueError, r"unknown class codes: \[3\]"),
    ],
)  # fmt: skip
def test_a_raster_zonation_that_does_not_fit_its_grid_is_refused(change, error, match):
    arguments = {"identifier": "zones", "encoded_codes": CODES, "encoded_to_zone": ZONES, "raster_support": raster_support(4, 4, **GRID)}  # fmt: skip

    with pytest.raises(error, match=match):
        RasterZonesSupportField(**{**arguments, **change})


def test_a_raster_zonation_reads_points_of_one_shape_only():
    field = RasterZonesSupportField(identifier="zones", encoded_codes=CODES, encoded_to_zone=ZONES, raster_support=raster_support(4, 4, **GRID))  # fmt: skip

    with pytest.raises(ValueError, match="same shape"):
        field.zone_id(np.zeros(2), np.zeros(3))
    np.testing.assert_array_equal(field.zone_id(np.array([0.0]), np.array([0.0])), [""])


@pytest.mark.parametrize(
    ("radii", "labels", "match"),
    [
        ([0.0], ["a", "b"], "strictly positive"),
        ([2.0, 1.0], ["a", "b", "c"], "strictly increasing"),
        ([1.0, 1.0], ["a", "b", "c"], "cannot contain duplicates"),
        ([1.0], ["a"], r"len\(radii_abs\) \+ 1"),
        ([1.0], ["a", " "], "cannot contain empty values"),
        ([1.0], ["a", "a"], "labels cannot contain duplicates"),
    ],
)
def test_rings_that_do_not_nest_are_refused(radii, labels, match):
    with pytest.raises(ValueError, match=match):
        GeneratedRingsSupportField(
            identifier="rings", center_x=0.0, center_y=0.0, radii_abs=radii, labels=labels
        )
