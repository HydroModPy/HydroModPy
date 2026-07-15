"""WP13 - the DRN fallback conductance is a true hydraulic conductance (m2/s).

When no conductance is configured, C = hk * cell_area / top_layer_thickness
(m/s * m2 / m = m2/s), shared by the MODFLOW 6 and MODFLOW-NWT backends so they
produce the same number for the same inputs.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
    collapse_identical_periods,
)
from hydromodpy.solver.modflow_common.drain_conductance import hk_fallback_drain_conductance
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def test_hk_fallback_conductance_formula_and_guards() -> None:
    # hk 1e-4 m/s, area 100 m2, thickness 5 m -> 2.0e-3 m2/s (not 1.0e-2 m3/s).
    assert hk_fallback_drain_conductance(
        hk=1e-4, cell_area=100.0, top_thickness=5.0
    ) == pytest.approx(2.0e-3)
    # Doubling the thickness halves the conductance.
    assert hk_fallback_drain_conductance(
        hk=1e-4, cell_area=100.0, top_thickness=10.0
    ) == pytest.approx(1.0e-3)
    # Degenerate guards stay finite and >= 1e-12.
    zero_k = hk_fallback_drain_conductance(hk=0.0, cell_area=100.0, top_thickness=5.0)
    assert zero_k == pytest.approx(1e-12)
    zero_thick = hk_fallback_drain_conductance(hk=1e-4, cell_area=100.0, top_thickness=0.0)
    assert np.isfinite(zero_thick) and zero_thick >= 1e-12


def _drn_mesh(thickness: float) -> SolverMesh:
    return SolverMesh.from_structured_arrays(
        nrow=1,
        ncol=6,
        top=np.full((1, 6), thickness),
        botm=np.zeros((1, 1, 6)),
        dx=10.0,
        dy=10.0,
    )


def _drn_model() -> SimpleNamespace:
    return SimpleNamespace(
        dem_mask=np.zeros(6, dtype=bool), nper=1, ncpl=6, hk=np.full((1, 6), 1e-4)
    )


def test_mf6_drn_fallback_conductance_is_m2_per_s() -> None:
    spd = build_drain_stress_period_data(
        _drn_model(),
        solver_mesh=_drn_mesh(5.0),
        drainage_cond_series=np.array([0.0]),
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )
    assert len(spd[0]) == 6
    cond = spd[0][0][3]
    assert cond == pytest.approx(2.0e-3)
    assert cond != pytest.approx(1.0e-2)


def test_mf6_drn_fallback_scales_inverse_with_top_thickness() -> None:
    spd = build_drain_stress_period_data(
        _drn_model(),
        solver_mesh=_drn_mesh(10.0),
        drainage_cond_series=np.array([0.0]),
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )
    assert spd[0][0][3] == pytest.approx(1.0e-3)


def test_mf6_drn_configured_conductance_bypasses_fallback() -> None:
    model = _drn_model()
    model.hk = np.full((1, 6), 99.0)  # large hk must be ignored
    spd = build_drain_stress_period_data(
        model,
        solver_mesh=_drn_mesh(5.0),
        drainage_cond_series=np.array([0.05]),
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )
    assert spd[0][0][3] == pytest.approx(0.05)


def test_mf6_drn_static_conductance_collapses_to_single_period() -> None:
    # A static drain over many periods emits period 0 only; MF6 reuses it for the
    # rest. This keeps a long daily run from rewriting every drain row per period.
    model = _drn_model()
    model.nper = 6940
    spd = build_drain_stress_period_data(
        model,
        solver_mesh=_drn_mesh(5.0),
        drainage_cond_series=np.zeros(6940),
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )
    assert sorted(spd) == [0]
    assert len(spd[0]) == 6


def test_mf6_drn_emits_period_only_when_conductance_changes() -> None:
    model = _drn_model()
    model.nper = 100
    series = np.zeros(100)
    series[10:] = 0.05
    series[60:] = 0.08
    spd = build_drain_stress_period_data(
        model,
        solver_mesh=_drn_mesh(5.0),
        drainage_cond_series=series,
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )
    assert sorted(spd) == [0, 10, 60]
    assert spd[10][0][3] == pytest.approx(0.05)
    assert spd[60][0][3] == pytest.approx(0.08)


def test_collapse_identical_periods_keeps_only_changes() -> None:
    spd = {0: [[1]], 1: [[1]], 2: [[2]], 3: [[2]], 4: [[2]], 5: [[3]]}
    assert collapse_identical_periods(spd) == {0: [[1]], 2: [[2]], 5: [[3]]}
    # Period 0 is always kept, even when every period is identical.
    assert collapse_identical_periods({0: [], 1: [], 2: []}) == {0: []}


def test_nwt_drn_fallback_uses_same_shared_helper() -> None:
    # NWT and MF6 both call hk_fallback_drain_conductance, so identical inputs give
    # the identical conductance. Guard the imported symbol is the same object.
    from hydromodpy.solver.modflow_nwt.nwt.payloads import well_drainage

    assert well_drainage.hk_fallback_drain_conductance is hk_fallback_drain_conductance
    mf6_value = build_drain_stress_period_data(
        _drn_model(),
        solver_mesh=_drn_mesh(5.0),
        drainage_cond_series=np.array([0.0]),
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )[0][0][3]
    nwt_value = well_drainage.hk_fallback_drain_conductance(
        hk=1e-4, cell_area=100.0, top_thickness=5.0
    )
    assert mf6_value == pytest.approx(nwt_value) == pytest.approx(2.0e-3)
