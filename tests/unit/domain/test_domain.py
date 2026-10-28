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
from tests._helpers.domain_cases import NODATA, X0, Y0, raster_support, surface, tilted_top

DEM = np.array([[110.0, 120.0], [100.0, 90.0]])


def _flat(elevation: object) -> dict:
    return {"depth_model": {"kind": "flat_substratum", "substratum_elevation": elevation}}


def _raster(top: Surface, values, *, kind: str = "raster_substratum", **depth_model) -> Domain:
    source = values if isinstance(values, Surface) else surface(values, name="raw")
    return build_domain(
        {"depth_model": {"kind": kind, **depth_model}}, surface_topo=top, substratum_source=source
    )


def _surfaces_layering(*tables: dict) -> dict:
    return {"layers": {"genmtd_lay": "surfaces", "layer": list(tables)}}


@pytest.mark.parametrize("config", [None, {}, DomainConfig()], ids=["none", "mapping", "section"])
def test_the_default_domain_hangs_a_constant_thickness_under_the_top(config):
    domain = Domain(config, surface_topo=Surface(name="surface_topo", values=DEM))

    thickness = float(DomainConfig().depth_model.thickness)
    np.testing.assert_allclose(domain.substratum.as_array(), DEM - thickness)
    assert domain.georeferencing == {} and domain.layer_bases == {}


def test_a_domain_config_of_another_type_is_refused():
    with pytest.raises(TypeError, match="DomainConfig instance or a mapping"):
        Domain(["constant_thickness"], surface_topo=Surface(name="surface_topo", values=DEM))


@pytest.mark.parametrize("thickness", [30.0, "30.0 m", "0.03 km"])
def test_a_constant_thickness_shifts_the_top_down(thickness):
    config = {"depth_model": {"kind": "constant_thickness", "thickness": thickness}}

    domain = Domain(config, surface_topo=Surface(name="surface_topo", values=DEM))

    np.testing.assert_allclose(domain.surface_topo.as_array(), DEM)
    np.testing.assert_allclose(domain.substratum.as_array(), DEM - 30.0)


@pytest.mark.parametrize("written", [-12.5, "-12.5 m", "-0.0125 km"])
def test_a_flat_substratum_takes_inline_units_like_the_thickness(written):
    domain = Domain(_flat(written), surface_topo=Surface(name="surface_topo", values=DEM))

    np.testing.assert_allclose(domain.substratum.as_array(), -12.5)


def test_a_flat_substratum_clamps_the_cells_at_or_below_it_and_refuses_one_above_all():
    """Cells dipping to the substratum get no aquifer; a substratum above all terrain is refused."""
    dem = np.array([[5.0, 6.0], [7.0, 8.0]])

    domain = Domain(_flat(6.0), surface_topo=Surface(name="surface_topo", values=dem))

    np.testing.assert_allclose(domain.substratum.as_array(), [[4.0, 5.0], [6.0, 6.0]])
    assert bool((domain.substratum.as_array() < dem).all())
    with pytest.raises(ValueError, match="no aquifer would remain"):
        Domain(_flat(100.0), surface_topo=Surface(name="surface_topo", values=dem))


def test_the_georeferencing_is_read_off_the_support_of_the_top():
    support = RasterSupport(crs="EPSG:2154", dx=50.0, dy=60.0, xmin=100.0, xmax=200.0, ymin=300.0, ymax=400.0, nrows=1, ncols=2)  # fmt: skip

    domain = Domain(surface_topo=Surface(name="surface_topo", values=np.array([[10.0, 12.0]]), support=support))  # fmt: skip

    assert domain.georeferencing == {
        "crs": "EPSG:2154", "dx": 50.0, "dy": 60.0, "xmin": 100.0, "xmax": 200.0, "ymin": 300.0, "ymax": 400.0,
    }  # fmt: skip


def test_an_elevation_raster_of_top_minus_50_is_a_constant_thickness_of_50():
    top = tilted_top()

    raster = _raster(top, top.as_array() - 50.0).substratum.as_array()

    constant = build_domain(DomainConfig.with_thickness(50.0), surface_topo=top).substratum
    np.testing.assert_array_equal(raster, constant.as_array())


def test_a_thickness_raster_of_50_is_a_constant_thickness_of_50():
    top = tilted_top()

    raster = _raster(top, np.full((6, 8), 50.0), kind="raster_thickness").substratum.as_array()

    np.testing.assert_array_equal(raster, top.as_array() - 50.0)


def test_a_flat_elevation_raster_is_a_flat_substratum_on_every_cell_carrying_data():
    top = tilted_top()

    raster = _raster(top, np.full((6, 8), 60.0)).substratum.as_array()

    flat = build_domain(_flat(60.0), surface_topo=top).substratum.as_array()
    np.testing.assert_array_equal(raster, flat)


def test_offset_moves_and_scale_multiplies_the_raster():
    top = tilted_top()

    bottom = _raster(
        top, np.full((6, 8), 20.0), kind="raster_thickness", scale=2.0, offset="3 m"
    ).substratum.as_array()

    np.testing.assert_allclose(bottom, top.as_array() - 40.0 + 3.0)


def test_a_finer_raster_of_a_plane_averages_back_to_the_plane():
    def plane(nrows: int, cell: float) -> np.ndarray:
        rows, cols = np.mgrid[0:nrows, 0 : nrows * 4 // 3]
        return 0.01 * (cols + 0.5) * cell + 0.02 * (nrows - rows - 0.5) * cell

    fine = surface(plane(12, 12.5), name="raw", cell=12.5)

    bottom = _raster(tilted_top(), fine).substratum.as_array()

    np.testing.assert_allclose(bottom, plane(6, 25.0), atol=1e-6)


def test_a_raster_in_another_crs_is_reprojected_onto_the_grid_of_the_top():
    """A constant field in WGS84 around Rennes, much larger than the domain."""
    wgs84 = surface(
        np.full((40, 40), 42.0), name="raw", cell=0.01, x0=-2.0, y0=47.9, crs="EPSG:4326"
    )

    np.testing.assert_allclose(_raster(tilted_top(), wgs84).substratum.as_array(), 42.0)


def test_a_raster_covering_only_the_catchment_serves_a_watershed_extent():
    catchment = np.zeros((6, 8), dtype=bool)
    catchment[1:5, 2:6] = True
    watershed_top = surface(np.where(catchment, tilted_top().as_array(), NODATA))

    bottom = _raster(watershed_top, np.where(catchment, 50.0, NODATA)).substratum.as_array()

    np.testing.assert_array_equal(bottom[catchment], 50.0)
    np.testing.assert_array_equal(bottom[~catchment], NODATA)


@pytest.mark.parametrize(
    ("values", "match"),
    [
        (np.pad(np.full((4, 4), 50.0), ((1, 1), (2, 2)), constant_values=NODATA), "leaves 32 of the 48 cells"),
        (np.full((6, 4), 50.0), "leaves 24 of the 48 cells"),
    ],
    ids=["catchment_raster_on_a_box", "smaller_raster"],
)  # fmt: skip
def test_a_raster_that_leaves_a_domain_cell_without_value_is_refused(values, match):
    with pytest.raises(DataContractViolation, match=match):
        _raster(tilted_top(), values)


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
        (tilted_top(), {"depth_model": {"kind": "raster_substratum"}}, None, ConfigError, r"\[data.substratum\]"),
        (tilted_top(), DomainConfig.with_thickness(50.0), np.full((6, 8), 50.0), ValueError, "does not read one"),
        (tilted_top(), {"depth_model": {"kind": "raster_substratum"}}, tilted_top().as_array() + 1.0, ValueError, "no aquifer would remain"),
        (Surface(name="surface_topo", values=DEM), {"depth_model": {"kind": "raster_substratum"}}, DEM, ValueError, "no RasterSupport"),
        (surface(np.full((2, 2), NODATA)), {"depth_model": {"kind": "raster_substratum"}}, DEM, ValueError, "holds no cell"),
    ],
    ids=["raster_kind_without_raster", "raster_to_another_kind", "above_the_top_everywhere", "top_without_support", "top_without_cell"],
)  # fmt: skip
def test_the_substratum_refusals(top, config, source, error, match):
    raw = None if source is None else surface(source, name="raw")

    with pytest.raises(error, match=match):
        build_domain(config, surface_topo=top, substratum_source=raw)


def test_a_layer_base_is_placed_on_the_grid_of_the_top_and_keeps_its_nodata():
    top = surface(np.where(np.eye(6, 8, dtype=bool), NODATA, tilted_top().as_array()))
    config = _surfaces_layering({"name": "a", "surface": "rock"}, {"name": "b"})
    rock = surface(np.full((12, 16), 70.0), name="raw", cell=12.5)

    domain = build_domain(config, surface_topo=top, layer_base_sources={"rock": rock})

    base = domain.layer_bases["rock"].as_array()
    np.testing.assert_array_equal(base[np.eye(6, 8, dtype=bool)], NODATA)
    np.testing.assert_array_equal(base[~np.eye(6, 8, dtype=bool)], 70.0)


def test_a_top_without_nodata_makes_every_cell_a_domain_cell():
    top = surface(tilted_top().as_array(), nodata=None)
    config = {"depth_model": {"kind": "raster_thickness"}, **_surfaces_layering({"name": "a", "surface": "rock"}, {"name": "b"})}  # fmt: skip
    flat = {"rock": surface(np.full((6, 8), 70.0), name="raw", nodata=None)}

    domain = build_domain(config, surface_topo=top, substratum_source=surface(np.full((6, 8), 10.0), name="raw"), layer_base_sources=flat)  # fmt: skip

    np.testing.assert_allclose(domain.substratum.as_array(), top.as_array() - 10.0)
    np.testing.assert_array_equal(domain.layer_bases["rock"].as_array(), 70.0)


@pytest.mark.parametrize(
    ("top", "layers", "sources", "error", "match"),
    [
        (tilted_top(), {}, {"rock": np.full((6, 8), 70.0)}, ValueError, r"\['rock'\] were given, and \[domain.layers\] reads none"),
        (tilted_top(), _surfaces_layering({"name": "a", "surface": "rock"}, {"name": "b"}), {}, ConfigError, r"reads the base surfaces \['rock'\]"),
        (Surface(name="surface_topo", values=DEM), _surfaces_layering({"name": "a", "surface": "rock"}, {"name": "b"}), {"rock": DEM}, ValueError, "no RasterSupport to place a layer base"),
        (tilted_top(), _surfaces_layering({"name": "a", "surface": "rock"}, {"name": "b"}), {"rock": np.full((6, 4), 70.0)}, DataContractViolation, "'rock' leaves 24 of the 48 cells"),
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

    domain.substratum = Surface(name="substratum", values=np.full((6, 8), np.nan))
    with pytest.raises(ValueError, match="no finite values"):
        _ = domain.z_interfaces
    domain.substratum = None
    with pytest.raises(ValueError, match="requires a substratum"):
        _ = domain.z_interfaces


def test_a_zone_is_stored_and_read_under_its_lower_case_id():
    domain = build_domain(None, surface_topo=Surface(name="surface_topo", values=DEM))
    zone = object()

    domain.set_zone(" Geology ", zone)

    assert domain.get_zone("GEOLOGY") is zone
    assert domain.get_zone("catchment") is None
    for call in (domain.set_zone, domain.get_zone, domain.resolve_spatial_support):
        with pytest.raises(ValueError, match="cannot be empty"):
            call(" ", *([zone] if call == domain.set_zone else []))


def test_a_domain_without_zone_ids_takes_any_zone():
    domain = Domain(surface_topo=Surface(name="surface_topo", values=DEM))

    domain.set_zone("lithofacies", "zones")

    assert domain.zones == {"lithofacies": "zones"}


def test_a_spatial_support_resolves_by_zone_key_then_by_field_identifier():
    domain = Domain(surface_topo=Surface(name="surface_topo", values=DEM))
    geology = SimpleNamespace(identifier="field_geology")
    domain.set_zone("geology", geology)

    assert domain.resolve_spatial_support("Geology") is geology
    assert domain.resolve_spatial_support("field_geology") is geology
    assert domain.resolve_spatial_support("field_catchment") is None

    domain.set_zone("geology_copy", SimpleNamespace(identifier="field_geology"))
    with pytest.raises(ValueError, match="Multiple domain zones match"):
        domain.resolve_spatial_support("field_geology")


def test_the_grid_of_a_raster_depth_model_is_the_grid_of_the_top():
    """The substratum is written on the support of the top, whatever the source grid."""
    domain = _raster(tilted_top(), surface(np.full((3, 4), 40.0), name="raw", cell=50.0))

    assert domain.substratum.support is domain.surface_topo.support
    assert domain.substratum.support == raster_support(6, 8, x0=X0, y0=Y0)
