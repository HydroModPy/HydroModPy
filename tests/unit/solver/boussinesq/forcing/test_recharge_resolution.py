"""The Boussinesq resolver gives one recharge rate (m/s) or one rate per cell for each period.

A source with no fields and no stations recharges nothing. A cell-wise array must have one value
per cell. The mesh is a committed triangle bundle.
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


def test_active_recharge_without_config() -> None:
    cfg = resolver(active_sinks_sources=("recharge",), recharge=None)

    assert cfg.resolve_recharge_series(3) == (0.0, 0.0, 0.0)


EMPTY_SOURCES = [
    pytest.param(SimpleNamespace(has_fields=False, has_points=True, points=()), id="no station"),
    pytest.param(SimpleNamespace(has_fields=False, has_points=False), id="no data"),
]


@pytest.mark.parametrize("source", EMPTY_SOURCES)
def test_empty_source_recharges_nothing(source) -> None:
    res = resolver()

    arrays = res.resolve_heterogeneous_recharge_series(
        heterogeneous_source=source, nper=2, first_clim="mean", interpolation_method="nearest"
    )

    assert len(arrays) == 2
    for values in arrays:
        np.testing.assert_array_equal(values, np.zeros(res.mesh.n_cells))


def test_no_period_gives_no_array() -> None:
    res = resolver()

    assert res.apply_first_clim_to_cellwise_recharge(raw_arrays={}, nper=0, first_clim="mean") == ()


def test_refuses_the_wrong_cell_count() -> None:
    res = resolver()

    with pytest.raises(ValueError, match="one value per Boussinesq cell; period 0 has 3"):
        res.apply_first_clim_to_cellwise_recharge(
            raw_arrays={0: np.ones(3)}, nper=1, first_clim="mean"
        )
    with pytest.raises(ValueError, match="mapping cannot be empty"):
        res.apply_first_clim_to_cellwise_recharge(raw_arrays={}, nper=1, first_clim="mean")
