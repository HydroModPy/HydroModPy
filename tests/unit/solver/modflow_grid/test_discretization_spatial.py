"""The vertical part of a regular grid, built from its two surfaces.

``StructuredGridBuilder`` of :mod:`hydromodpy.solver.modflow_grid.discretization_spatial`.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.solver.modflow_grid.discretization_spatial import StructuredGridBuilder
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface


def _surface_from_array(
    values: np.ndarray,
    *,
    xmin: float = 0.0,
    ymin: float = 0.0,
    dx: float = 1.0,
    dy: float = 1.0,
    crs: str = "EPSG:2154",
    nodata: float = -9999.0,
    name: str = "surface",
) -> Surface:
    arr = np.asarray(values, dtype=float)
    nrows, ncols = arr.shape
    support = RasterSupport(
        crs=crs,
        dx=dx,
        dy=dy,
        xmin=xmin,
        xmax=xmin + (dx * ncols),
        ymin=ymin,
        ymax=ymin + (dy * nrows),
        nrows=nrows,
        ncols=ncols,
        nodata=nodata,
    )
    return Surface(name=name, values=arr, support=support)


def test_build_from_surfaces_uses_absolute_top_and_bottom():
    top = np.array([[120.0, 121.0], [122.0, 123.0]], dtype=float)
    bottom = np.array([[20.0, 21.0], [22.0, 23.0]], dtype=float)
    top_surface = _surface_from_array(top, name="top")
    bottom_surface = _surface_from_array(bottom, name="bottom")

    sgrid = StructuredGridBuilder().build_from_surfaces(
        top_surface=top_surface,
        bottom_surface=bottom_surface,
        vertical_config=VerticalGridConfig(
            genmtd_lay="constant",
            nlay=3,
            nodata=-9999.0,
        ),
    )

    assert sgrid.nlay == 3
    assert np.allclose(np.asarray(sgrid.top, dtype=float), top)
    assert np.allclose(np.asarray(sgrid.botm[-1], dtype=float), bottom)


def test_build_from_surfaces_rejects_domain_mismatch():
    top = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    bot = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float)
    top_surface = _surface_from_array(top, xmin=0.0, ymin=0.0, name="top")
    bottom_surface = _surface_from_array(bot, xmin=1.0, ymin=0.0, name="bottom")

    with pytest.raises(ValueError, match="Domain extent mismatch"):
        _ = StructuredGridBuilder().build_from_surfaces(
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config={"genmtd_lay": "constant", "nlay": 2},
        )


def _with_support(surface: Surface, **changes: object) -> Surface:
    """The same surface on a support with *changes*."""
    support = replace(surface.support, **changes)
    return Surface(name=surface.name, values=surface.as_array(), support=support)


def _build(top: Surface, bottom: Surface, **kwargs):
    config = kwargs.pop("vertical_config", {"genmtd_lay": "constant", "nlay": 2})
    return StructuredGridBuilder().build_from_surfaces(
        top_surface=top, bottom_surface=bottom, vertical_config=config, **kwargs
    )


TOP = np.array([[120.0, 121.0], [122.0, 123.0]])
BOTTOM = np.array([[20.0, 21.0], [22.0, 23.0]])


def test_a_support_without_steps_is_accepted():
    top = _with_support(_surface_from_array(TOP, dx=4.0, dy=3.0), dx=None, dy=None)
    bottom = _surface_from_array(BOTTOM, dx=4.0, dy=3.0)

    sgrid = _build(top, bottom)

    assert sgrid.nlay == 2
    np.testing.assert_allclose(sgrid.top, TOP)


def test_a_support_without_steps_is_checked_on_the_steps_of_its_extent():
    flipped = {"dx": None, "dy": None, "xmin": 8.0, "xmax": 0.0}
    top = _with_support(_surface_from_array(TOP, ymin=100.0, dx=4.0, dy=3.0), **flipped)
    bottom = _with_support(_surface_from_array(BOTTOM, ymin=100.0, dx=4.0, dy=3.0), **flipped)

    with pytest.raises(ValueError, match=r"Invalid support cell sizes: dx=-4.0, dy=3.0"):
        _build(top, bottom)


def test_a_nodata_cell_is_outside_the_domain_in_every_layer():
    top = TOP.copy()
    top[0, 1] = -9999.0

    sgrid = _build(_surface_from_array(top), _surface_from_array(BOTTOM))

    assert np.all(sgrid.idomain[:, 0, 1] == 0)
    assert np.all(sgrid.idomain[:, [0, 1, 1], [0, 0, 1]] == 1)
    assert np.all(sgrid.botm[:, 0, 1] == -9999.0)


def test_the_layers_end_on_the_base_surfaces_they_name():
    base = np.array([[70.0, 71.0], [72.0, 73.0]])
    layering = VerticalGridConfig(
        genmtd_lay="surfaces",
        layer=[{"name": "weathered", "surface": "weathered_base"}, {"name": "fissured"}],
    )

    sgrid = _build(
        _surface_from_array(TOP),
        _surface_from_array(BOTTOM),
        vertical_config=layering,
        base_surfaces={"weathered_base": _surface_from_array(base, name="weathered_base")},
    )

    assert sgrid.nlay == 2
    np.testing.assert_allclose(sgrid.botm[0], base)
    np.testing.assert_allclose(sgrid.botm[1], BOTTOM)


def test_a_layer_base_on_another_grid_is_refused():
    layering = VerticalGridConfig(
        genmtd_lay="surfaces",
        layer=[{"name": "weathered", "surface": "weathered_base"}, {"name": "fissured"}],
    )
    coarse = _surface_from_array(np.full((1, 1), 70.0), dx=2.0, dy=2.0)

    with pytest.raises(
        ValueError, match=r"layer base 'weathered_base' has shape \(1, 1\), the top \(2, 2\)"
    ):
        _build(
            _surface_from_array(TOP),
            _surface_from_array(BOTTOM),
            vertical_config=layering,
            base_surfaces={"weathered_base": coarse},
        )


def test_a_bottom_on_another_grid_is_refused():
    fine_bottom = _surface_from_array(np.full((4, 4), 20.0), dx=0.5, dy=0.5)

    with pytest.raises(ValueError, match=r"must have the same discretization.*resample_to_shape"):
        _build(_surface_from_array(TOP), fine_bottom)


@pytest.mark.parametrize(
    ("step", "message"),
    [("dx", r"dx=-1.0, dy=1.0"), ("dy", r"dx=1.0, dy=-1.0")],
)
def test_a_support_with_a_negative_cell_size_is_refused(step: str, message: str):
    # A north-up raster transform carries a negative y step; the support must not.
    top = _with_support(_surface_from_array(TOP), **{step: -1.0})

    with pytest.raises(ValueError, match=rf"Invalid support cell sizes: {message}"):
        _build(top, _surface_from_array(BOTTOM))
