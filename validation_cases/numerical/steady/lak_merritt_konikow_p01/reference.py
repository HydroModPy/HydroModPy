"""Upstream reference build of ex-gwf-lak-p01 (Merritt & Konikow 2000, test 1).

This wraps the published MODFLOW 6 example: a single surface lake on a five-layer
aquifer, driven by left/right constant head, areal recharge and ET. The LAK
CONNECTIONDATA is built with the upstream ``flopy.mf6.utils.get_lak_connections``
helper, the authoritative tool for the structural comparison. The model runs in
the example's native feet/days units; ``comparison.py`` brings the result into
meters so it can be compared against the HMP SI build.

The lake is laid on layer 0 only (the same single-layer footprint the HMP DISV
builder uses), rather than the published two-layer embedded lake, so both sides
share an identical footprint and the structural / numerical comparison stays
apples-to-apples.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

from .geometry import LakeP01Geometry, load_geometry


@dataclass(frozen=True, slots=True)
class LakeRunResult:
    """Scalar outputs of one finished LAK run, in a single declared length unit.

    ``length_unit`` records the unit ``final_stage`` / ``lake_gwf_exchange`` are
    expressed in so ``comparison.py`` can convert both runs onto a common basis.
    ``connection_counts`` maps the upper-cased claktype to its count.
    """

    label: str
    workspace: Path
    length_unit: str
    final_stage: float
    lake_gwf_in: float
    lake_gwf_out: float
    budget_percent_discrepancy: float
    n_connections: int
    connection_counts: dict[str, int] = field(default_factory=dict)

    @property
    def lake_gwf_gross_exchange(self) -> float:
        """Gross lake-aquifer flux (total magnitude exchanged in either direction).

        This is the robust comparison metric: at near-equilibrium the net flux is
        a tiny difference of two large, near-equal terms, so it is dominated by
        the staircased-perimeter asymmetry; the gross magnitude is stable.
        """
        return self.lake_gwf_in + self.lake_gwf_out


def _lake_table(geometry: LakeP01Geometry) -> list[tuple[float, float, float]]:
    """Vertical-walled stage/volume/area abacus in feet (area constant, dV linear)."""
    foot_area = geometry.lake_footprint_area_ft2
    bed = geometry.bed_elevation_ft
    return [
        (float(stage), float(foot_area * (stage - bed)), float(foot_area))
        for stage in geometry.abacus_stage_ft
    ]


def build_reference_simulation(workspace: Path, *, geometry: LakeP01Geometry | None = None):
    """Build the upstream-equivalent feet/days MF6 simulation with a LAK package."""
    import flopy

    geom = geometry if geometry is not None else load_geometry()
    exe = str(ensure_solver_binary("mf6"))
    nlay, nrow, ncol = geom.nlay, geom.nrow, geom.ncol
    shape3d = (nlay, nrow, ncol)

    sim = flopy.mf6.MFSimulation(sim_name="lakp01ref", sim_ws=str(workspace), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=(geom.tdis_period_days,),
        time_units="days",
    )
    flopy.mf6.ModflowIms(
        sim,
        print_option="summary",
        complexity="MODERATE",
        linear_acceleration="bicgstab",
        outer_maximum=geom.outer_maximum,
        outer_dvclose=geom.outer_dvclose,
        inner_maximum=geom.inner_maximum,
        inner_dvclose=geom.inner_dvclose,
        rcloserecord=f"{geom.rclose} strict",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="lakp01ref", newtonoptions="newton", save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf,
        length_units="feet",
        nlay=nlay,
        nrow=nrow,
        ncol=ncol,
        delr=geom.delr_ft,
        delc=geom.delc_ft,
        idomain=np.ones(shape3d, dtype=int),
        top=geom.top_ft,
        botm=list(geom.botm_ft),
    )
    flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=1,
        k=geom.k11_ft_per_day,
        k33=list(geom.k33_ft_per_day),
        save_specific_discharge=True,
    )
    flopy.mf6.ModflowGwfsto(
        gwf, iconvert=1, sy=geom.specific_yield, ss=geom.specific_storage_per_day
    )
    flopy.mf6.ModflowGwfic(gwf, strt=geom.strt_ft)

    chd_spd: list[list[Any]] = []
    for k in range(nlay):
        chd_spd += [[k, i, 0, geom.head_left_ft] for i in range(nrow)]
        chd_spd += [[k, i, ncol - 1, geom.head_right_ft] for i in range(nrow)]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd)
    flopy.mf6.ModflowGwfrcha(gwf, recharge=geom.recharge_ft_per_day)

    lake_map = np.ones(shape3d, dtype=np.int32) * -1
    lake_map[0, geom.row_start : geom.row_stop, geom.col_start : geom.col_stop] = 0
    lake_map = np.ma.masked_where(lake_map < 0, lake_map)
    idomain_wlakes, pakdata_dict, lak_conn = flopy.mf6.utils.get_lak_connections(
        gwf.modelgrid, lake_map, bedleak=geom.bedleak_per_day
    )

    table = _lake_table(geom)
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        boundnames=True,
        print_stage=True,
        save_flows=True,
        nlakes=1,
        ntables=1,
        packagedata=[[0, geom.stage_init_ft, pakdata_dict[0], "lac0"]],
        connectiondata=lak_conn,
        tables=[[0, "lac0.laktab"]],
        perioddata={
            0: [
                [0, "RAINFALL", geom.rainfall_ft_per_day],
                [0, "EVAPORATION", geom.evaporation_ft_per_day],
            ]
        },
        surfdep=geom.surfdep_ft,
        stage_filerecord="lakp01ref.lak.stage",
        budget_filerecord="lakp01ref.lak.cbc",
        budgetcsv_filerecord="lakp01ref.lak.budget.csv",
    )
    flopy.mf6.ModflowUtllaktab(
        gwf, nrow=len(table), ncol=3, table=table, filename="lac0.laktab", parent_file=lak
    )
    gwf.dis.idomain = idomain_wlakes
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="lakp01ref.hds",
        budget_filerecord="lakp01ref.cbc",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
    )
    return sim, gwf, lak_conn


def run_reference(workspace: Path, *, geometry: LakeP01Geometry | None = None) -> LakeRunResult:
    """Build, run, and summarise the upstream feet/days LAK reference."""
    sim, gwf, lak_conn = build_reference_simulation(workspace, geometry=geometry)
    sim.write_simulation(silent=True)
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise RuntimeError(f"Reference LAK run did not converge:\n{buff}")

    final_stage = float(np.ravel(gwf.lak.output.stage().get_data())[-1])
    gwf_in, gwf_out, percent = read_lake_budget_csv(workspace / "lakp01ref.lak.budget.csv")
    counts = Counter(str(row[3]).upper() for row in lak_conn)
    return LakeRunResult(
        label="reference",
        workspace=workspace,
        length_unit="feet",
        final_stage=final_stage,
        lake_gwf_in=gwf_in,
        lake_gwf_out=gwf_out,
        budget_percent_discrepancy=percent,
        n_connections=len(lak_conn),
        connection_counts=dict(counts),
    )


def read_lake_budget_csv(path: Path) -> tuple[float, float, float]:
    """Return ``(GWF_IN, GWF_OUT, PERCENT_DIFFERENCE)`` from a LAK budget CSV.

    The LAK ``budgetcsv`` is one row per time step; we read the last (steady) row.
    GWF_IN/GWF_OUT are the lake-aquifer exchange terms and their difference is the
    net flux from the lake's point of view.
    """
    import csv

    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Empty LAK budget CSV: {path}")
    last = rows[-1]
    gwf_in = float(last["GWF_IN"])
    gwf_out = float(last["GWF_OUT"])
    percent = float(last["PERCENT_DIFFERENCE"])
    return gwf_in, gwf_out, percent


__all__ = [
    "LakeRunResult",
    "build_reference_simulation",
    "read_lake_budget_csv",
    "run_reference",
]
