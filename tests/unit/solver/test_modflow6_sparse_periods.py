"""Sparse stress-period emission: MF6 repeats the last PERIOD block.

Long daily chronicles pay FloPy's per-period block-header bookkeeping
(quadratic in the number of provided periods), so the builders emit only
change points: deduplicated recharge/EVT payloads, a single zero AUX block,
and STO settings at steady/transient transitions.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.builders import (
    collapse_identical_periods,
    empty_recharge_aux,
    sto_period_settings,
)


def test_collapse_drops_consecutive_identical_arrays() -> None:
    a = np.full(4, 1.0)
    b = np.full(4, 2.0)
    spd = {0: a, 1: a.copy(), 2: b, 3: b.copy(), 4: a.copy()}
    collapsed = collapse_identical_periods(spd)
    assert sorted(collapsed) == [0, 2, 4]
    np.testing.assert_allclose(collapsed[4], a)


def test_collapse_keeps_list_payload_change_points() -> None:
    rows_a = [[0, 1, 2.0]]
    rows_b = [[0, 1, 3.0]]
    spd = {0: rows_a, 1: list(rows_a), 2: [], 3: [], 4: rows_b}
    collapsed = collapse_identical_periods(spd)
    assert sorted(collapsed) == [0, 2, 4]
    assert collapsed[2] == []


def test_collapse_always_keeps_first_period() -> None:
    spd = {0: np.zeros(3)}
    assert sorted(collapse_identical_periods(spd)) == [0]


def test_empty_recharge_aux_emits_single_period_block() -> None:
    model = SimpleNamespace(ncpl=5, nper=100)
    aux = empty_recharge_aux(model)
    assert sorted(aux) == [0]
    np.testing.assert_allclose(aux[0][0], np.zeros(5))


def test_sto_period_settings_emits_change_points_only() -> None:
    steady_state, transient = sto_period_settings([True, False, False, False])
    assert steady_state == {0: True}
    assert transient == {1: True}


def test_sto_period_settings_all_transient() -> None:
    steady_state, transient = sto_period_settings([False, False, False])
    assert steady_state == {}
    assert transient == {0: True}


def test_sto_period_settings_alternating_flags() -> None:
    steady_state, transient = sto_period_settings([False, True, True, False])
    assert steady_state == {1: True}
    assert transient == {0: True, 3: True}
