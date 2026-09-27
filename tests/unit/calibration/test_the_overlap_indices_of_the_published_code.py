"""The secondary diagnostics other codes of the method recorded.

``D_so / D_os`` is the ratio the v1 example 10 kept as ``DSO/DOS`` and the
authors' dichotomy branched on. The overlap indices are ``fuzzy`` and
``total_length`` of the authors' published code (Zenodo 8311547,
``objective_function.py``). All of them are components, never the cost.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from hydromodpy.calibration.metrics.downslope_network import secondary_diagnostics
from hydromodpy.core.stream_geometry import CriterionSupports

# Ten cells in the catchment, one outside it. Four cells of each area 100 m2
# are simulated, three are mapped, two of them in common.
KEEP = np.array([True] * 10 + [False])
SIMULATED = np.array([1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1], dtype=bool)
MAPPED = np.array([0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0], dtype=bool)
AREAS = np.full(11, 100.0)


def _supports() -> CriterionSupports:
    support_so = SIMULATED & KEEP
    support_os = MAPPED & KEEP
    return CriterionSupports(
        keep=KEEP,
        support_so=support_so,
        support_os=support_os,
        valid=support_so & MAPPED,
        excess=support_so & ~MAPPED,
        missing=support_os & ~SIMULATED,
        seepage=support_so,
    )


def test_the_indices_follow_the_published_definitions() -> None:
    out = secondary_diagnostics(d_so=30.0, d_os=20.0, supports=_supports(), cell_area_m2=AREAS)

    # So = 3, Sm = 4, Si = 2, Ni = 1, Nc = 5, No = 10 - 3 = 7.
    ea = 1.0 - abs(4.0 - 3.0) / 3.0
    sa = 1.0 - 2.0 / 3.0
    na = 1.0 - 1.0 / 7.0
    assert out["n_neither"] == 5.0
    assert out["overlap_Ea"] == pytest.approx(ea)
    assert out["overlap_Sa"] == pytest.approx(sa)
    assert out["overlap_Na"] == pytest.approx(na)
    assert out["overlap_E"] == pytest.approx(ea * sa * na)
    assert out["D_so_over_D_os"] == pytest.approx(1.5)


def test_a_length_is_the_sum_of_the_cell_sizes_on_the_scored_support() -> None:
    out = secondary_diagnostics(d_so=1.0, d_os=1.0, supports=_supports(), cell_area_m2=AREAS)

    # The simulated cell outside the catchment is not counted.
    assert out["L_sim_m"] == pytest.approx(40.0)
    assert out["L_obs_m"] == pytest.approx(30.0)


def test_the_ratio_is_not_a_number_when_d_os_is_zero_or_d_so_is_missing() -> None:
    supports = _supports()

    zero = secondary_diagnostics(d_so=5.0, d_os=0.0, supports=supports, cell_area_m2=AREAS)
    empty = secondary_diagnostics(d_so=math.nan, d_os=5.0, supports=supports, cell_area_m2=AREAS)

    assert math.isnan(zero["D_so_over_D_os"])
    assert math.isnan(empty["D_so_over_D_os"])
