"""The soil EVTA surface tracks the DRN elevation, not always the raw top.

The soil reservoir has already taken the ETP it could, so what the EVT package
draws is what would otherwise reach the drain: the same elevation the DRN
builder gives the cell (``drain_discharge_band``), lowered further by
``surface_offset`` when the file asks for it.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.builders.recharge import build_soil_evta_payload
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

_NCPL = 4


def _mesh() -> SolverMesh:
    top = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    botm = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float)
    return SolverMesh.from_structured_arrays(nrow=2, ncol=2, top=top, botm=np.stack([botm]))


def _model(*, drain_band_depth_m: float, surface_offset_m: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        ncpl=_NCPL,
        nper=1,
        model_name_mf6="m",
        drain_band_depth_m=drain_band_depth_m,
        _soil_etp_rate={0: np.full(_NCPL, 1.0e-8)},
        _soil_evt_surface_offset_m=surface_offset_m,
        _soil_evt_extinction_depth_m=1.0,
    )


def _surface(model: SimpleNamespace, *, drain_active: bool) -> np.ndarray:
    mesh = _mesh()
    payload = build_soil_evta_payload(
        model,
        mesh,
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=drain_active,
        shared_dir=None,
    )
    assert payload is not None
    _, surface, _ = payload
    return surface


def test_a_zero_band_depth_leaves_the_surface_at_the_top() -> None:
    model = _model(drain_band_depth_m=0.0)
    surface = _surface(model, drain_active=True)
    np.testing.assert_allclose(surface, [10.0, 11.0, 12.0, 13.0])


def test_a_one_metre_band_lowers_the_surface_by_half_the_band() -> None:
    model = _model(drain_band_depth_m=1.0)
    surface = _surface(model, drain_active=True)
    np.testing.assert_allclose(surface, [9.5, 10.5, 11.5, 12.5])


def test_an_inactive_drain_leaves_the_surface_at_the_top() -> None:
    model = _model(drain_band_depth_m=1.0)
    surface = _surface(model, drain_active=False)
    np.testing.assert_allclose(surface, [10.0, 11.0, 12.0, 13.0])


def test_a_surface_offset_lowers_the_surface_further() -> None:
    model = _model(drain_band_depth_m=0.0, surface_offset_m=0.3)
    surface = _surface(model, drain_active=True)
    np.testing.assert_allclose(surface, np.array([10.0, 11.0, 12.0, 13.0]) - 0.3)
