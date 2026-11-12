"""The Boussinesq resolver puts each well in the triangle that holds it, with its rate in m3/s.

A well is given by absolute or relative map coordinates on layer 0. A rate comes from a number or
from a forcing, and is converted to m3/s.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.mesh.io.bundle import load_catchment_mesh_bundle
from hydromodpy.solver.boussinesq.forcing import BoussinesqForcingResolver
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from tests._helpers.mesh_cases import MESH_BUNDLES
from tests._helpers.model_factory import make_model

pytestmark = pytest.mark.fast

BUNDLE = "hantush_recharge_mound_tri_conforming"


def resolver(**members) -> BoussinesqForcingResolver:
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(MESH_BUNDLES / BUNDLE))
    return BoussinesqForcingResolver(mesh=mesh, inputs=make_model(**members))


def at_centroid(res: BoussinesqForcingResolver, cell: int) -> SimpleNamespace:
    return SimpleNamespace(
        kind="absolute_xy",
        layer=0,
        x=float(res.mesh.cell_centroid_x_m[cell]),
        y=float(res.mesh.cell_centroid_y_m[cell]),
    )


def test_no_well_gives_no_flux() -> None:
    res = resolver(active_sinks_sources=("wells",), wells={})

    assert res.resolve_well_flux_by_period(2).shape == (2, res.mesh.n_cells)
    assert not res.resolve_well_flux_by_period(2).any()


def test_well_flux_lands_in_its_cell() -> None:
    res = resolver()
    cell = 5
    well = SimpleNamespace(location=at_centroid(res, cell), flux=-1.0e-3, forcing=None)
    res = resolver(active_sinks_sources=("wells",), wells={"w1": well})

    flux = res.resolve_well_flux_by_period(2)

    expected = np.zeros((2, res.mesh.n_cells))
    expected[:, cell] = -1.0e-3  # one well pumping 1 L/s in every period
    np.testing.assert_allclose(flux, expected)


def test_relative_position_is_a_share_of_the_extent() -> None:
    res = resolver()
    cell = 7
    x_rel = (res.mesh.cell_centroid_x_m[cell] - res.mesh.x_min_m) / (
        res.mesh.x_max_m - res.mesh.x_min_m
    )
    y_rel = (res.mesh.cell_centroid_y_m[cell] - res.mesh.y_min_m) / (
        res.mesh.y_max_m - res.mesh.y_min_m
    )
    location = SimpleNamespace(kind="relative_xy", layer=0, x_rel=x_rel, y_rel=y_rel)

    assert res.resolve_well_cell_index("w1", SimpleNamespace(location=location)) == cell


def test_forcing_rate_is_converted_to_m3_per_s() -> None:
    res = resolver()
    forcing = SimpleNamespace(kind="constant", value=86400.0, units="m3/day")

    rate = res.resolve_well_flux_series("w1", SimpleNamespace(forcing=forcing), 3)

    np.testing.assert_allclose(rate, [1.0] * 3)  # 86400 m3/day / 86400 s/day


def test_refuses_a_forcing_that_is_not_finite() -> None:
    res = resolver()
    forcing = SimpleNamespace(kind="values", values=[1.0, float("nan")], units="m3/s")

    with pytest.raises(ValueError, match="wells.w1.forcing must be finite"):
        res.resolve_well_flux_series("w1", SimpleNamespace(forcing=forcing), 2)


REFUSALS = [
    pytest.param(
        SimpleNamespace(kind="absolute_xy", layer=1, x=0.0, y=0.0),
        NotImplementedError,
        "supports only layer 0",
        id="second layer",
    ),
    pytest.param(
        SimpleNamespace(kind="cell", layer=0),
        NotImplementedError,
        "structured-grid cell addressing",
        id="cell addressing",
    ),
    pytest.param(
        SimpleNamespace(kind="polar", layer=0),
        ValueError,
        "Unsupported well location mode for 'w1'",
        id="unknown mode",
    ),
]


@pytest.mark.parametrize(("location", "error", "message"), REFUSALS)
def test_refusals(location, error, message) -> None:
    res = resolver()

    with pytest.raises(error, match=message):
        res.resolve_well_cell_index("w1", SimpleNamespace(location=location))
