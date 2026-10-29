"""The domain: its top, the substratum its depth model places, its layer bases, its zones.

The raster depth models are attacked through the kinds they must reproduce: an
elevation raster of top minus 50 is a constant thickness of 50.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain.build import build_domain
from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.domain.domain_config import DomainConfig
from tests._helpers.domain_cases import NODATA, raster_support, surface, surfaces_table, tilted_top

DEM = np.array([[110.0, 120.0], [100.0, 90.0]])
RASTER = {"depth_model": {"kind": "raster_substratum"}}


def _dem(values=DEM) -> Surface:
    return Surface(name="surface_topo", values=values)


def _flat(elevation: object) -> dict:
    return {"depth_model": {"kind": "flat_substratum", "substratum_elevation": elevation}}


def _raster(top: Surface, values, *, kind: str = "raster_substratum", **depth_model) -> Domain:
    source = values if isinstance(values, Surface) else surface(values, name="raw")
    return build_domain({"depth_model": {"kind": kind, **depth_model}}, surface_topo=top, substratum_source=source)  # fmt: skip


ROCK_LAYERING = {"layers": surfaces_table({"name": "a", "surface": "rock"}, {"name": "b"})}


@pytest.mark.parametrize("config", [None, {}, DomainConfig()], ids=["none", "mapping", "section"])
def test_the_default_domain_hangs_a_constant_thickness_and_reads_the_georeferencing_off_the_top(config):  # fmt: skip
    domain = Domain(config, surface_topo=_dem())

    np.testing.assert_allclose(domain.substratum.as_array(), DEM - float(DomainConfig().depth_model.thickness))  # fmt: skip
    assert domain.georeferencing == {} and domain.layer_bases == {}
    with pytest.raises(TypeError, match="DomainConfig instance or a mapping"):
        Domain(["constant_thickness"], surface_topo=_dem())
    reference = {"crs": "EPSG:2154", "dx": 50.0, "dy": 60.0, "xmin": 100.0, "xmax": 200.0, "ymin": 300.0, "ymax": 400.0}  # fmt: skip
    top = Surface(name="surface_topo", values=np.array([[10.0, 12.0]]), support=RasterSupport(**reference, nrows=1, ncols=2))  # fmt: skip
    assert Domain(config, surface_topo=top).georeferencing == reference


@pytest.mark.parametrize(
    ("config", "bottom"),
    [
        *[({"depth_model": {"kind": "constant_thickness", "thickness": t}}, DEM - 30.0) for t in (30.0, "30.0 m", "0.03 km")],
        *[(_flat(written), -12.5) for written in (-12.5, "-12.5 m", "-0.0125 km")],
    ],
    ids=["thickness", "thickness_in_m", "thickness_in_km", "flat", "flat_in_m", "flat_in_km"],
)  # fmt: skip
def test_a_depth_model_reads_inline_units_and_leaves_the_top_alone(config, bottom):
    domain = Domain(config, surface_topo=_dem())

    np.testing.assert_allclose(domain.surface_topo.as_array(), DEM)
    np.testing.assert_allclose(domain.substratum.as_array(), bottom)


def test_a_flat_substratum_clamps_the_cells_at_or_below_it_and_refuses_one_above_all():
    dem = np.array([[5.0, 6.0], [7.0, 8.0]])

    domain = Domain(_flat(6.0), surface_topo=_dem(dem))

    np.testing.assert_allclose(domain.substratum.as_array(), [[4.0, 5.0], [6.0, 6.0]])
    assert bool((domain.substratum.as_array() < dem).all())
    with pytest.raises(ValueError, match="no aquifer would remain"):
        Domain(_flat(100.0), surface_topo=_dem(dem))


@pytest.mark.parametrize(
    ("kind", "values", "depth_model", "expected", "rtol"),
    [
        ("raster_substratum", lambda top: top - 50.0, {}, lambda top: build_domain(DomainConfig.with_thickness(50.0), surface_topo=top).substratum.as_array(), 0.0),
        ("raster_thickness", lambda top: np.full((6, 8), 50.0), {}, lambda top: top.as_array() - 50.0, 0.0),
        ("raster_substratum", lambda top: np.full((6, 8), 60.0), {}, lambda top: build_domain(_flat(60.0), surface_topo=top).substratum.as_array(), 0.0),
        ("raster_thickness", lambda top: np.full((6, 8), 20.0), {"scale": 2.0, "offset": "3 m"}, lambda top: top.as_array() - 40.0 + 3.0, 1e-7),
    ],
    ids=["elevation_of_top_minus_50_is_a_constant_thickness_of_50", "thickness_of_50_is_a_constant_thickness_of_50",
         "flat_elevation_is_a_flat_substratum", "offset_moves_and_scale_multiplies"],
)  # fmt: skip
def test_a_raster_depth_model_reproduces_the_kind_it_stands_for(kind, values, depth_model, expected, rtol):  # fmt: skip
    top = tilted_top()

    bottom = _raster(top, values(top.as_array()), kind=kind, **depth_model).substratum.as_array()

    np.testing.assert_allclose(bottom, expected(top), rtol=rtol, atol=0)


def _plane(nrows: int, cell: float) -> np.ndarray:
    rows, cols = np.mgrid[0:nrows, 0 : nrows * 4 // 3]
    return 0.01 * (cols + 0.5) * cell + 0.02 * (nrows - rows - 0.5) * cell


@pytest.mark.parametrize(
    ("source", "expected", "atol"),
    [
        (lambda: surface(_plane(12, 12.5), name="raw", cell=12.5), _plane(6, 25.0), 1e-6),
        (lambda: surface(np.full((40, 40), 42.0), name="raw", cell=0.01, x0=-2.0, y0=47.9, crs="EPSG:4326"), 42.0, 0.0),
        (lambda: surface(np.full((3, 4), 40.0), name="raw", cell=50.0), 40.0, 0.0),
    ],
    ids=["a_finer_raster_of_a_plane_averages_back_to_the_plane", "a_wgs84_field_around_rennes_is_reprojected", "a_coarser_raster"],
)  # fmt: skip
def test_a_raster_depth_model_is_written_on_the_grid_of_the_top(source, expected, atol):
    domain = _raster(tilted_top(), source())

    np.testing.assert_allclose(domain.substratum.as_array(), expected, atol=atol)
    assert domain.substratum.support is domain.surface_topo.support
    assert domain.substratum.support == raster_support(6, 8)


def test_a_raster_covering_only_the_catchment_serves_a_watershed_extent():
    catchment = np.zeros((6, 8), dtype=bool)
    catchment[1:5, 2:6] = True
    watershed_top = surface(np.where(catchment, tilted_top().as_array(), NODATA))

    bottom = _raster(watershed_top, np.where(catchment, 50.0, NODATA)).substratum.as_array()

    np.testing.assert_array_equal(bottom[catchment], 50.0)
    np.testing.assert_array_equal(bottom[~catchment], NODATA)


def test_a_raster_above_the_top_is_lowered_to_top_minus_min_thickness(caplog):
    top = tilted_top()
    values = top.as_array() - 30.0
    values[0, 0] = top.as_array()[0, 0] + 5.0

    with caplog.at_level(logging.WARNING):
        bottom = _raster(top, values, min_thickness="2 m").substratum.as_array()

    assert bottom[0, 0] == top.as_array()[0, 0] - 2.0
    np.testing.assert_array_equal(bottom.ravel()[1:], (top.as_array() - 30.0).ravel()[1:])
    assert "on 1 of the 48 cells" in caplog.text


@pytest.mark.parametrize(
    ("top", "config", "source", "error", "match"),
    [
        (tilted_top(), RASTER, None, ConfigError, r"\[data.substratum\]"),
        (tilted_top(), DomainConfig.with_thickness(50.0), np.full((6, 8), 50.0), ValueError, "does not read one"),
        (tilted_top(), RASTER, tilted_top().as_array() + 1.0, ValueError, "no aquifer would remain"),
        (_dem(), RASTER, DEM, ValueError, "no RasterSupport"),
        (surface(np.full((2, 2), NODATA)), RASTER, DEM, ValueError, "holds no cell"),
        (tilted_top(), RASTER, np.pad(np.full((4, 4), 50.0), ((1, 1), (2, 2)), constant_values=NODATA), DataContractViolation, "leaves 32 of the 48 cells"),
        (tilted_top(), RASTER, np.full((6, 4), 50.0), DataContractViolation, "leaves 24 of the 48 cells"),
    ],
    ids=["raster_kind_without_raster", "raster_to_another_kind", "above_the_top_everywhere", "top_without_support",
         "top_without_cell", "catchment_raster_on_a_box_leaves_cells_without_value", "smaller_raster_leaves_cells_without_value"],
)  # fmt: skip
def test_the_substratum_refusals(top, config, source, error, match):
    raw = None if source is None else surface(source, name="raw")

    with pytest.raises(error, match=match):
        build_domain(config, surface_topo=top, substratum_source=raw)


def test_a_layer_base_is_placed_on_the_grid_of_the_top_and_keeps_its_nodata():
    hole = np.eye(6, 8, dtype=bool)
    top = surface(np.where(hole, NODATA, tilted_top().as_array()))
    rock = surface(np.full((12, 16), 70.0), name="raw", cell=12.5)

    base = build_domain(ROCK_LAYERING, surface_topo=top, layer_base_sources={"rock": rock}).layer_bases["rock"].as_array()  # fmt: skip

    np.testing.assert_array_equal(base[hole], NODATA)
    np.testing.assert_array_equal(base[~hole], 70.0)


def test_a_top_without_nodata_makes_every_cell_a_domain_cell():
    top = surface(tilted_top().as_array(), nodata=None)
    config = {"depth_model": {"kind": "raster_thickness"}, **ROCK_LAYERING}
    flat = {"rock": surface(np.full((6, 8), 70.0), name="raw", nodata=None)}

    domain = build_domain(config, surface_topo=top, substratum_source=surface(np.full((6, 8), 10.0), name="raw"), layer_base_sources=flat)  # fmt: skip

    np.testing.assert_allclose(domain.substratum.as_array(), top.as_array() - 10.0)
    np.testing.assert_array_equal(domain.layer_bases["rock"].as_array(), 70.0)


@pytest.mark.parametrize(
    ("top", "layers", "sources", "error", "match"),
    [
        (tilted_top(), {}, {"rock": np.full((6, 8), 70.0)}, ValueError, r"\['rock'\] were given, and \[domain.layers\] reads none"),
        (tilted_top(), ROCK_LAYERING, {}, ConfigError, r"reads the base surfaces \['rock'\]"),
        (_dem(), ROCK_LAYERING, {"rock": DEM}, ValueError, "no RasterSupport to place a layer base"),
        (tilted_top(), ROCK_LAYERING, {"rock": np.full((6, 4), 70.0)}, DataContractViolation, "'rock' leaves 24 of the 48 cells"),
    ],
    ids=["base_nobody_reads", "base_missing", "top_without_support", "base_too_small"],
)  # fmt: skip
def test_the_layer_base_refusals(top, layers, sources, error, match):
    given = {name: surface(values, name="raw") for name, values in sources.items()}

    with pytest.raises(error, match=match):
        build_domain(layers, surface_topo=top, layer_base_sources=given)


def test_the_interfaces_are_the_mean_top_and_the_mean_bottom():
    domain = build_domain(DomainConfig.with_thickness(30.0), surface_topo=tilted_top())

    top_mean = float(tilted_top().as_array().mean())
    np.testing.assert_allclose(domain.z_interfaces, [top_mean, top_mean - 30.0])
    for substratum, match in [(Surface(name="substratum", values=np.full((6, 8), np.nan)), "no finite values"), (None, "requires a substratum")]:  # fmt: skip
        domain.substratum = substratum
        with pytest.raises(ValueError, match=match):
            _ = domain.z_interfaces


def test_a_zone_is_stored_under_its_lower_case_id_and_a_support_resolves_by_key_then_by_identifier():  # fmt: skip
    domain = build_domain(None, surface_topo=_dem())
    zone = object()

    domain.set_zone(" Geology ", zone)

    assert (domain.get_zone("GEOLOGY"), domain.get_zone("catchment")) == (zone, None)
    for call in (domain.set_zone, domain.get_zone, domain.resolve_spatial_support):
        with pytest.raises(ValueError, match="cannot be empty"):
            call(" ", *([zone] if call == domain.set_zone else []))
    anything = Domain(surface_topo=_dem())
    anything.set_zone("lithofacies", "zones")
    assert anything.zones == {"lithofacies": "zones"}
    domain = Domain(surface_topo=_dem())
    geology = SimpleNamespace(identifier="field_geology")
    domain.set_zone("geology", geology)

    assert domain.resolve_spatial_support("Geology") is geology
    assert domain.resolve_spatial_support("field_geology") is geology
    assert domain.resolve_spatial_support("field_catchment") is None
    domain.set_zone("geology_copy", SimpleNamespace(identifier="field_geology"))
    with pytest.raises(ValueError, match="Multiple domain zones match"):
        domain.resolve_spatial_support("field_geology")
