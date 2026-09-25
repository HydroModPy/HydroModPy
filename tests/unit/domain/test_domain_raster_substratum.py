"""The ``raster`` depth model, attacked through the two kinds it must reproduce."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain import Domain, DomainConfig
from hydromodpy.spatial.domain.build import build_domain

NODATA = -9999.0
X0, Y0 = 350_000.0, 6_790_000.0


def _support(
    nrows: int,
    ncols: int,
    *,
    dx: float = 25.0,
    x0: float = X0,
    y0: float = Y0,
    crs: str = "EPSG:2154",
    nodata: float | None = NODATA,
) -> RasterSupport:
    return RasterSupport(
        crs=crs,
        dx=dx,
        dy=dx,
        xmin=x0,
        xmax=x0 + ncols * dx,
        ymin=y0,
        ymax=y0 + nrows * dx,
        nrows=nrows,
        ncols=ncols,
        nodata=nodata,
    )


def _top(nrows: int = 6, ncols: int = 8) -> Surface:
    rows, cols = np.mgrid[0:nrows, 0:ncols]
    values = 100.0 + 2.0 * cols - 1.5 * rows
    return Surface(name="surface_topo", values=values.astype(float), support=_support(nrows, ncols))


def _raster_domain(top: Surface, source: Surface, **depth_model) -> Domain:
    return build_domain(
        DomainConfig.model_validate({"depth_model": {"kind": "raster", **depth_model}}),
        surface_topo=top,
        substratum_source=source,
    )


def test_an_elevation_raster_of_top_minus_50_is_a_constant_thickness_of_50() -> None:
    top = _top()
    source = Surface(name="raw", values=top.as_array() - 50.0, support=_support(6, 8))

    raster = _raster_domain(top, source).substratum.as_array()
    constant = build_domain(DomainConfig.with_thickness(50.0), surface_topo=top).substratum

    np.testing.assert_array_equal(raster, constant.as_array())


def test_a_thickness_raster_of_50_is_a_constant_thickness_of_50() -> None:
    top = _top()
    source = Surface(name="raw", values=np.full((6, 8), 50.0), support=_support(6, 8))

    raster = _raster_domain(top, source, quantity="thickness").substratum.as_array()

    np.testing.assert_array_equal(raster, top.as_array() - 50.0)


def test_a_flat_elevation_raster_is_a_flat_substratum_on_every_cell_carrying_data() -> None:
    top = _top()
    source = Surface(name="raw", values=np.full((6, 8), 60.0), support=_support(6, 8))

    raster = _raster_domain(top, source).substratum.as_array()
    flat = build_domain(
        DomainConfig.model_validate(
            {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 60.0}}
        ),
        surface_topo=top,
    ).substratum.as_array()

    np.testing.assert_array_equal(raster, flat)


def test_offset_moves_and_scale_multiplies_the_raster() -> None:
    top = _top()
    thickness = Surface(name="raw", values=np.full((6, 8), 20.0), support=_support(6, 8))

    bottom = _raster_domain(
        top, thickness, quantity="thickness", scale=2.0, offset="3 m"
    ).substratum.as_array()

    np.testing.assert_allclose(bottom, top.as_array() - 40.0 + 3.0)


def test_scale_is_refused_on_an_elevation_raster() -> None:
    with pytest.raises(ValidationError, match="scale multiplies a thickness raster"):
        DomainConfig.model_validate({"depth_model": {"kind": "raster", "scale": 2.0}})


def test_a_finer_raster_of_a_plane_averages_back_to_the_plane() -> None:
    top = _top()
    fine = _support(12, 16, dx=12.5)
    rows, cols = np.mgrid[0:12, 0:16]
    x = X0 + (cols + 0.5) * 12.5
    y = Y0 + 12 * 12.5 - (rows + 0.5) * 12.5
    plane = 0.01 * (x - X0) + 0.02 * (y - Y0)
    source = Surface(name="raw", values=plane, support=fine)

    bottom = _raster_domain(top, source).substratum.as_array()

    rows, cols = np.mgrid[0:6, 0:8]
    x = X0 + (cols + 0.5) * 25.0
    y = Y0 + 6 * 25.0 - (rows + 0.5) * 25.0
    np.testing.assert_allclose(bottom, 0.01 * (x - X0) + 0.02 * (y - Y0), atol=1e-6)


def test_a_raster_in_another_crs_is_reprojected_onto_the_grid_of_the_top() -> None:
    top = _top()
    # A constant field in WGS84 around Rennes, much larger than the domain.
    source = Surface(
        name="raw",
        values=np.full((40, 40), 42.0),
        support=RasterSupport(
            crs="EPSG:4326",
            dx=0.01,
            dy=0.01,
            xmin=-2.0,
            xmax=-1.6,
            ymin=47.9,
            ymax=48.3,
            nrows=40,
            ncols=40,
            nodata=NODATA,
        ),
    )
    # The top sits at Lambert-93 (350 km, 6790 km), inside that box.
    bottom = _raster_domain(top, source).substratum.as_array()

    np.testing.assert_allclose(bottom, 42.0)


def test_a_raster_covering_only_the_catchment_serves_a_watershed_extent() -> None:
    top = _top()
    catchment = np.zeros((6, 8), dtype=bool)
    catchment[1:5, 2:6] = True
    watershed_top = Surface(
        name="surface_topo",
        values=np.where(catchment, top.as_array(), NODATA),
        support=top.support,
    )
    source = Surface(
        name="raw",
        values=np.where(catchment, 50.0, NODATA),
        support=_support(6, 8),
    )

    bottom = _raster_domain(watershed_top, source).substratum.as_array()

    np.testing.assert_array_equal(bottom[catchment], 50.0)
    np.testing.assert_array_equal(bottom[~catchment], NODATA)


def test_the_same_raster_is_refused_on_a_box_extent() -> None:
    top = _top()
    catchment = np.zeros((6, 8), dtype=bool)
    catchment[1:5, 2:6] = True
    source = Surface(
        name="raw",
        values=np.where(catchment, 50.0, NODATA),
        support=_support(6, 8),
    )

    with pytest.raises(DataContractViolation, match="leaves 32 of the 48 cells"):
        _raster_domain(top, source)


def test_a_raster_smaller_than_the_domain_is_refused() -> None:
    top = _top()
    source = Surface(name="raw", values=np.full((6, 4), 50.0), support=_support(6, 4))

    with pytest.raises(DataContractViolation, match="leaves 24 of the 48 cells"):
        _raster_domain(top, source)


def test_active_cells_narrow_the_cells_the_raster_must_cover() -> None:
    top = _top()
    active = np.zeros((6, 8), dtype=bool)
    active[:, :4] = True
    source = Surface(name="raw", values=np.full((6, 4), 50.0), support=_support(6, 4))

    domain = build_domain(
        DomainConfig.model_validate({"depth_model": {"kind": "raster"}}),
        surface_topo=top,
        substratum_source=source,
        active_cells=active,
    )

    np.testing.assert_array_equal(domain.substratum.as_array()[active], 50.0)


def test_a_raster_above_the_top_is_lowered_to_top_minus_min_thickness(caplog) -> None:
    top = _top()
    values = top.as_array() - 30.0
    values[0, 0] = top.as_array()[0, 0] + 5.0
    source = Surface(name="raw", values=values, support=_support(6, 8))

    with caplog.at_level(logging.WARNING):
        bottom = _raster_domain(top, source, min_thickness="2 m").substratum.as_array()

    assert bottom[0, 0] == top.as_array()[0, 0] - 2.0
    np.testing.assert_array_equal(bottom.ravel()[1:], (top.as_array() - 30.0).ravel()[1:])
    assert "on 1 of the 48 cells" in caplog.text


def test_a_raster_above_the_top_everywhere_is_refused() -> None:
    top = _top()
    source = Surface(name="raw", values=top.as_array() + 1.0, support=_support(6, 8))

    with pytest.raises(ValueError, match="no aquifer would remain"):
        _raster_domain(top, source)


def test_the_raster_kind_without_a_raster_is_refused() -> None:
    with pytest.raises(ConfigError, match=r"\[data.substratum\]"):
        Domain(
            DomainConfig.model_validate({"depth_model": {"kind": "raster"}}),
            surface_topo=_top(),
        )


def test_a_raster_handed_to_another_kind_is_refused() -> None:
    source = Surface(name="raw", values=np.full((6, 8), 50.0), support=_support(6, 8))

    with pytest.raises(ValueError, match="does not read one"):
        build_domain(
            DomainConfig.with_thickness(50.0), surface_topo=_top(), substratum_source=source
        )


def test_reprojected_onto_its_own_grid_copies_and_turns_the_sentinel_into_nan() -> None:
    values = np.arange(48, dtype=float).reshape(6, 8)
    values[2, 3] = NODATA
    surface = Surface(name="raw", values=values, support=_support(6, 8))

    moved = surface.reprojected_onto(_support(6, 8)).as_array()

    assert np.isnan(moved[2, 3])
    moved[2, 3] = values[2, 3]
    np.testing.assert_array_equal(moved, values)
