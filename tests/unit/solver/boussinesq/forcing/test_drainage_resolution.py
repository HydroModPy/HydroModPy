"""The Boussinesq resolver reads the ocean stage (m) and the drainage conductance per period.

The sea holds every cell whose top lies at or below the highest stage of a period. A drainage
conductance is one number per period. A boundary of the wrong kind is refused by name.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.boussinesq.forcing import BoussinesqForcingResolver
from tests._helpers.model_factory import make_model

pytestmark = pytest.mark.fast


def resolver_with(conditions: dict, active: tuple[str, ...], mesh=None):
    bundle = BoundaryConditionBundle(conditions=conditions, active_ids=active)
    return BoussinesqForcingResolver(mesh=mesh, inputs=make_model(boundaries=bundle))


def coast() -> SimpleNamespace:
    """Four cells with tops at 0, 1, 2 and 5 m, and one boundary edge on each of the first three."""
    return SimpleNamespace(
        n_cells=4,
        z_top_m=np.array([0.0, 1.0, 2.0, 5.0]),
        boundary_edge_mask=np.array([True, True, True, False]),
        edge_is_river=np.array([False, True, False, False]),
        edge_cell_a=np.array([0, 1, 2, 3]),
    )


NO_STAGE = [
    pytest.param(None, id="no stage"),
    pytest.param(np.array([]), id="empty stage"),
]


@pytest.mark.parametrize("stage", NO_STAGE)
def test_no_stage_holds_nothing(stage) -> None:
    resolver = resolver_with({}, (), mesh=coast())

    assert resolver.ocean_support_edge_indices(stage).size == 0
    assert not resolver.ocean_supported_cell_mask(stage).any()
    masks = resolver.ocean_supported_cell_masks_by_period(stage, nper=2)
    assert len(masks) == 2
    assert all(mask.shape == (4,) and not mask.any() for mask in masks)


def test_cells_at_or_below_the_stage() -> None:
    resolver = resolver_with({}, (), mesh=coast())

    # Stage 1 m holds the tops at 0 and 1 m. The river edge on cell 1 is left out.
    np.testing.assert_array_equal(resolver.ocean_support_edge_indices(1.0), [0])
    np.testing.assert_array_equal(
        resolver.ocean_supported_cell_mask(1.0), [True, True, False, False]
    )
    masks = resolver.ocean_supported_cell_masks_by_period(np.array([0.0, 2.0]), nper=2)
    np.testing.assert_array_equal(masks[0], [True, False, False, False])
    np.testing.assert_array_equal(masks[1], [True, True, True, False])


def test_ocean_series_per_period() -> None:
    boundary = SimpleNamespace(kind="Dirichlet", value=[0.5, 1.5])
    resolver = resolver_with({"ocean": boundary}, ("ocean",))

    np.testing.assert_allclose(resolver.resolve_ocean_series(2), [0.5, 1.5])
    assert resolver_with({}, ()).resolve_ocean_series(2) is None


def test_drainage_conductance_per_period() -> None:
    boundary = SimpleNamespace(kind="drain", value=1.0e-6)
    resolver = resolver_with({"drainage": boundary}, ("drainage",))

    np.testing.assert_allclose(resolver.resolve_drainage_conductance_series(3), [1.0e-6] * 3)
    np.testing.assert_array_equal(resolver_with({}, ()).resolve_drainage_conductance_series(3), 0.0)


REFUSALS = [
    pytest.param(
        lambda: resolver_with({}, ("ocean",)).resolve_ocean_series(1),
        "'ocean' is missing",
        id="ocean listed active but not configured",
    ),
    pytest.param(
        lambda: resolver_with(
            {"ocean": SimpleNamespace(kind="neumann", value=0.0)}, ("ocean",)
        ).resolve_ocean_series(1),
        "must be Dirichlet",
        id="ocean of another kind",
    ),
    pytest.param(
        lambda: resolver_with({}, (), mesh=coast()).ocean_supported_cell_masks_by_period(
            np.array([0.0, 1.0, 2.0]), nper=2
        ),
        "must match nper",
        id="stage series of the wrong length",
    ),
    pytest.param(
        lambda: resolver_with({}, ("drainage",)).resolve_drainage_conductance_series(1),
        "'drainage' is missing",
        id="drainage listed active but not configured",
    ),
    pytest.param(
        lambda: resolver_with(
            {"drainage": SimpleNamespace(kind="river", value=1.0)}, ("drainage",)
        ).resolve_drainage_conductance_series(1),
        "must be of kind drain",
        id="drainage of another kind",
    ),
]


@pytest.mark.parametrize(("call", "message"), REFUSALS)
def test_refusals(call, message) -> None:
    with pytest.raises(ValueError, match=message):
        call()
