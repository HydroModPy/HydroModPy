"""Sparse stress-period input and adaptive time stepping of MODFLOW 6 (times in s).

MF6 repeats the last PERIOD block, so the builders write only change points:
deduplicated recharge payloads, one zero AUX block and STO flags at steady or
transient switches. ATS records carry zero-based period indices and a step
that may shrink below the declared step but never grow back to the period.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.boundary_conditions import collapse_identical_periods
from hydromodpy.solver.modflow6.builders.period_forcing import (
    constant_forcing_value,
    resolve_use_ts6,
    sto_period_settings,
)
from hydromodpy.solver.modflow6.builders.recharge import empty_recharge_aux
from hydromodpy.solver.modflow6.builders.solver_options import build_ats_perioddata

PERLEN_S = 2678400.0  # 31 days


def ats_records(*, nstp, steady, perlen=PERLEN_S):
    return build_ats_perioddata(
        perlen=np.full(len(nstp), perlen, dtype=float),
        nstp=np.asarray(nstp, dtype=int),
        steady=np.asarray(steady, dtype=bool),
        dtmin_s=1.0,
    )


def test_collapse_array_payloads():
    a = np.full(4, 1.0)
    b = np.full(4, 2.0)

    collapsed = collapse_identical_periods({0: a, 1: a.copy(), 2: b, 3: b.copy(), 4: a.copy()})

    assert sorted(collapsed) == [0, 2, 4]
    np.testing.assert_allclose(collapsed[4], a)


def test_collapse_list_payloads():
    rows_a = [[0, 1, 2.0]]
    rows_b = [[0, 1, 3.0]]

    collapsed = collapse_identical_periods({0: rows_a, 1: list(rows_a), 2: [], 3: [], 4: rows_b})

    assert sorted(collapsed) == [0, 2, 4]
    assert collapsed[2] == []


def test_collapse_keeps_first_period():
    assert sorted(collapse_identical_periods({0: np.zeros(3)})) == [0]


def test_empty_recharge_aux_is_one_block():
    aux = empty_recharge_aux(SimpleNamespace(ncpl=5, nper=100))

    assert sorted(aux) == [0]
    np.testing.assert_allclose(aux[0][0], np.zeros(5))


STO_SETTINGS = [
    pytest.param([True, False, False, False], {0: True}, {1: True}, id="steady then transient"),
    pytest.param([False, False, False], {}, {0: True}, id="all transient"),
    pytest.param([False, True, True, False], {1: True}, {0: True, 3: True}, id="alternating"),
]


@pytest.mark.parametrize(("steady", "steady_state", "transient"), STO_SETTINGS)
def test_sto_period_settings(steady, steady_state, transient):
    assert sto_period_settings(steady) == (steady_state, transient)


def test_ats_skips_steady_periods():
    records = ats_records(nstp=[1, 10, 10], steady=[True, False, False])

    assert [record[0] for record in records] == [1, 2]


def test_ats_indices_are_zero_based(tmp_path: Path):
    # FloPy adds one, so a 1-based record would shift every period and drop the last.
    records = ats_records(nstp=[10, 10], steady=[False, False])
    assert [record[0] for record in records] == [0, 1]

    sim = flopy.mf6.MFSimulation(sim_name="s", sim_ws=str(tmp_path), exe_name="mf6")
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=2,
        perioddata=[(PERLEN_S, 10, 1.0), (PERLEN_S, 10, 1.0)],
        time_units="seconds",
    )
    flopy.mf6.ModflowUtlats(tdis, maxats=len(records), perioddata=records)
    sim.write_simulation(silent=True)

    written = (tmp_path / "s.ats").read_text(encoding="utf-8").splitlines()
    start = written.index("BEGIN perioddata")
    ipers = [int(written[start + 1 + i].split()[0]) for i in range(len(records))]

    # The file MF6 reads is 1-based and names every declared period once.
    assert ipers == [1, 2]


def test_ats_step_stays_below_declared_step():
    (record,) = ats_records(nstp=[10], steady=[False])
    _iper, dt0, dtmin, dtmax, dtadj, dtfailadj = record

    declared_s = PERLEN_S / 10
    assert dt0 == pytest.approx(declared_s)
    # A larger dtmax would let ATS grow back to one step per period.
    assert dtmax == pytest.approx(declared_s)
    assert dtmin == 1.0
    # No growth, but a failed solve is still cut.
    assert dtadj == 1.0
    assert dtfailadj > 1.0


def test_ats_single_step_period():
    (record,) = ats_records(nstp=[1], steady=[False])

    assert record[1] == pytest.approx(PERLEN_S)
    assert record[3] == pytest.approx(PERLEN_S)


CONSTANT_VALUES = [
    pytest.param(None, None, id="no forcing"),
    pytest.param({"kind": "constant", "value": 3.0}, 3.0, id="constant mapping"),
    pytest.param({"value": SimpleNamespace(magnitude=2.0)}, 2.0, id="value with a unit magnitude"),
    pytest.param({"kind": "csv", "value": 3.0}, None, id="series is resolved later"),
    pytest.param({"value": None}, {"value": None}, id="empty value is returned whole"),
]


@pytest.mark.parametrize(("forcing", "expected"), CONSTANT_VALUES)
def test_constant_forcing_value(forcing, expected):
    assert constant_forcing_value(forcing) == expected


def test_constant_kind_without_value_stays_inline():
    # Nothing to read, but the declared kind still keeps it out of a TS6 file.
    forcing = {"kind": "constant"}

    assert resolve_use_ts6(forcing, mode="ts6", nper=500, min_periods=120) is False
