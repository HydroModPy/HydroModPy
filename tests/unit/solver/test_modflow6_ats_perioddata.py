"""Adaptive time stepping must target the right period and respect NSTP.

Two things go wrong silently here. FloPy converts the ``iper`` of an ATS record
to 1-based when it writes the file, so a record built 1-based lands one period
late and the last one falls off the end of the simulation. And MF6 ignores the
TDIS NSTP of a period ATS covers, so an unbounded ``dtmax`` lets it grow the
step back to the whole period, undoing the sub-stepping the run asked for.
"""

from __future__ import annotations

from pathlib import Path

import flopy
import numpy as np
import pytest

from hydromodpy.solver.modflow6.build import build_ats_perioddata


def _records(*, nstp: list[int], steady: list[bool], perlen: float = 2678400.0):
    return build_ats_perioddata(
        perlen=np.full(len(nstp), perlen, dtype=float),
        nstp=np.asarray(nstp, dtype=int),
        steady=np.asarray(steady, dtype=bool),
        dtmin_s=1.0,
    )


def test_steady_periods_carry_no_record() -> None:
    records = _records(nstp=[1, 10, 10], steady=[True, False, False])

    assert [record[0] for record in records] == [1, 2]


def test_indices_are_zero_based_for_flopy(tmp_path: Path) -> None:
    """FloPy adds one; a 1-based record would shift every period and drop the last."""
    perlen = 2678400.0
    records = _records(nstp=[10, 10], steady=[False, False], perlen=perlen)
    assert [record[0] for record in records] == [0, 1]

    sim = flopy.mf6.MFSimulation(sim_name="s", sim_ws=str(tmp_path), exe_name="mf6")
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=2,
        perioddata=[(perlen, 10, 1.0), (perlen, 10, 1.0)],
        time_units="seconds",
    )
    flopy.mf6.ModflowUtlats(tdis, maxats=len(records), perioddata=records)
    sim.write_simulation(silent=True)

    written = (tmp_path / "s.ats").read_text(encoding="utf-8").splitlines()
    start = written.index("BEGIN perioddata")
    ipers = [int(written[start + 1 + i].split()[0]) for i in range(len(records))]

    # The file MF6 reads is 1-based, and it names every declared period exactly once.
    assert ipers == [1, 2]


def test_ats_may_only_go_below_the_declared_step() -> None:
    perlen = 2678400.0
    (record,) = _records(nstp=[10], steady=[False], perlen=perlen)
    _iper, dt0, dtmin, dtmax, dtadj, dtfailadj = record

    declared = perlen / 10
    assert dt0 == pytest.approx(declared)
    # dtmax at perlen would let ATS grow back to a single step per period and
    # discard the sub-stepping the run declared.
    assert dtmax == pytest.approx(declared)
    assert dtmin == 1.0
    # No growth, but a failed solve is still cut.
    assert dtadj == 1.0
    assert dtfailadj > 1.0


def test_a_single_step_period_keeps_the_whole_period_as_its_step() -> None:
    perlen = 2678400.0
    (record,) = _records(nstp=[1], steady=[False], perlen=perlen)

    assert record[1] == pytest.approx(perlen)
    assert record[3] == pytest.approx(perlen)
