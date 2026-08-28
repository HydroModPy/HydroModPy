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
    # hk 1e-4 m/s, area 100 m2, BED 5 m -> 2.0e-3 m2/s (not 1.0e-2 m3/s).
    assert hk_fallback_drain_conductance(
        hk=1e-4, cell_area=100.0, bed_thickness=5.0, floor_m2_s=1e-12
    ) == pytest.approx(2.0e-3)
    # Doubling the bed thickness halves the conductance.
    assert hk_fallback_drain_conductance(
        hk=1e-4, cell_area=100.0, bed_thickness=10.0, floor_m2_s=1e-12
    ) == pytest.approx(1.0e-3)
    # A zero-K cell would emit a conductance MODFLOW reads as no drain at all.
    zero_k = hk_fallback_drain_conductance(
        hk=0.0, cell_area=100.0, bed_thickness=5.0, floor_m2_s=1e-12
    )
    assert zero_k == pytest.approx(1e-12)


def test_the_fallback_no_longer_guards_a_zero_thickness() -> None:
    """The bed thickness is a DECLARED, validated quantity, never mesh geometry.

    It used to be the layer thickness read off the mesh, which could be zero on
    a degenerate cell, hence a silent fallback to one metre. `gt=0.0` on
    `solver.drain_bed_thickness_m` now refuses zero at load, so the guard has no
    caller left and a zero here is a programming error, not a mesh accident.
    """
    from hydromodpy.solver.base.solver_config import SolverConfig

    with pytest.raises(Exception, match="drain_bed_thickness_m"):
        SolverConfig.model_validate({"drain_bed_thickness_m": 0.0})


def _drn_mesh(thickness: float) -> SolverMesh:
    return SolverMesh.from_structured_arrays(
        nrow=1,
        ncol=6,
        top=np.full((1, 6), thickness),
        botm=np.zeros((1, 1, 6)),
        dx=10.0,
        dy=10.0,
    )


def _drn_model(bed_thickness: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(
        dem_mask=np.zeros(6, dtype=bool),
        nper=1,
        ncpl=6,
        hk=np.full((1, 6), 1e-4),
        sink_fill=False,
        sink=None,
        drain_band_depth_m=0.0,
        drain_bed_thickness_m=bed_thickness,
        drain_conductance_floor_m2_s=1e-12,
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
    # bed 1 m : 1e-4 * 100 / 1 = 1e-2 m2/s. What this guards is the UNIT: the
    # value must stay a conductance in m2/s and never the m3/s a bare K * A
    # would give, which on this mesh would be 1e-4 * 100 = 1e-2 too... so the
    # discriminating check is the bed scaling, done just below.
    assert cond == pytest.approx(1.0e-2)
    doubled = build_drain_stress_period_data(
        _drn_model(bed_thickness=2.0),
        solver_mesh=_drn_mesh(5.0),
        drainage_cond_series=np.array([0.0]),
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )[0][0][3]
    assert doubled == pytest.approx(5.0e-3)


def test_mf6_drn_fallback_ignores_the_layer_thickness() -> None:
    """The property that REPLACES the old one, and it is the point of the change.

    The fallback used to divide by the LAYER thickness, so a thicker aquifer
    gave a less conductive drain. Head imposed by the drain to pass the recharge
    is ``dh = R * thickness / K``: at 30 m on the Nancon that made the drain the
    limiting resistance below K = 8.3e-6 m/s, inside the bracket a network
    calibration searches. A drain that is meant to be a seepage face must not
    depend on how deep the aquifer happens to be.
    """
    rows = {}
    for layer_thickness in (5.0, 10.0, 40.0):
        spd = build_drain_stress_period_data(
            _drn_model(),
            solver_mesh=_drn_mesh(layer_thickness),
            drainage_cond_series=np.array([0.0]),
            ocean_support_mask=np.zeros(6, dtype=bool),
            stream_support_mask=np.zeros(6, dtype=bool),
        )
        rows[layer_thickness] = spd[0][0][3]

    # bed 1 m by default: 1e-4 * 100 / 1 = 1e-2 m2/s, whatever the layer.
    for value in rows.values():
        assert value == pytest.approx(1.0e-2)


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
        hk=1e-4, cell_area=100.0, bed_thickness=1.0, floor_m2_s=1e-12
    )
    assert mf6_value == pytest.approx(nwt_value) == pytest.approx(1.0e-2)
