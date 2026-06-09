"""ex-gwf-lak-p02 (Merritt & Konikow 2000, test 2): 2 lakes + 22-reach SFR + MVR.

Reproduces the upstream MODFLOW 6 example with the FOUR water-mover transfers
(SFR -> LAK 1, LAK 1 -> SFR, SFR -> LAK 2, LAK 2 -> SFR at FACTOR 0.5) routed
through HydroModPy's package-agnostic MVR seam (:class:`MoverRecord` +
:func:`build_mvr_period_records` + :func:`mover_package_count`), which is the
code under validation. Everything else copies the published example verbatim
(grid, properties, LAK via ``get_lak_connections``, SFR tables) so any
disagreement isolates to the seam.

Published reference (MF6 examples doc, ex-gwf-lak-p02.tex): at the end of the
1,500-day simulation the stage of lake 1 converges to 116.98 ft and the stage of
lake 2 to 111.93 ft. The lake maps under ``data/`` are the example's USGS
distribution files.
"""

from __future__ import annotations

import csv
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hydromodpy.solver.modflow6.builders.mvr import (
    MoverRecord,
    build_mvr_period_records,
    mover_package_count,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.flow_adapter_helpers import _last_percent_discrepancy

_CASE_DIR = Path(__file__).parent
_SIM_NAME = "lakp02"

# --- ex-gwf-lak-p02 parameters (feet / days), copied verbatim ---------------- #
_NPER = 1
_NLAY, _NROW, _NCOL = 5, 27, 17
_TOP = 200.0
_BOTM = [102.0, 97.0, 87.0, 77.0, 67.0]
_STRT = 115.0
_K11 = 30.0
_K33 = 30.0
_SS = 3e-4
_SY = 0.2
_H1, _H2 = 160.0, 140.0
_RECHARGE = 0.0116
_ETVRATE = 0.0141
_ETVDEPTH = 15.0
_LAK_STRT = 130.0
_LAK_ETRATE = 0.0103
_LAK_BEDLEAK = 0.1
_TDIS_DS = ((1500.0, 200, 1.005),)

_DELR = np.array(
    [250.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 500.0, 500.0, 500.0, 500.0]
    + [500.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 250.0]
)
_DELC = np.array(
    [250.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 500.0, 500.0, 500.0, 500.0, 500.0]
    + [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 500.0, 500.0, 500.0, 500.0, 500.0]
    + [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 250.0]
)

_LAK_OUTLETS = [
    [0, 0, -1, "manning", 114.85, 5.0, 0.05, 8.206324419006205e-4],
    [1, 1, -1, "manning", 109.4286, 5.0, 0.05, 9.458197164349258e-4],
]
_LAK_SPD = [
    [0, "rainfall", _RECHARGE],
    [0, "evaporation", _LAK_ETRATE],
    [1, "rainfall", _RECHARGE],
    [1, "evaporation", _LAK_ETRATE],
]

_SFR_PAKDATA = [
    [0, 0, 1, 4, 1000, 5, 0.001103448, 123.94827, 0.5, 0.5, 0.050000001, 1, 1, 0],
    [1, 0, 2, 4, 1000, 5, 0.001103448, 122.84483, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [2, 0, 3, 4, 1000, 5, 0.001103448, 121.74138, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [3, 0, 3, 5, 1000, 5, 0.001103448, 120.63793, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [4, 0, 3, 6, 500, 5, 0.001103448, 119.81035, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [5, 0, 3, 7, 750, 5, 0.001103448, 119.12069, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [6, 0, 4, 7, 1000, 5, 0.001103448, 118.15517, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [7, 0, 5, 7, 1000, 5, 0.001103448, 117.05173, 0.5, 0.5, 0.050000001, 1, 1, 0],
    [8, 0, 11, 8, 1000, 5, 0.000820632, 114.43968, 0.5, 0.5, 0.050000001, 1, 1, 0],
    [9, 0, 12, 8, 1000, 5, 0.000820632, 113.61905, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [10, 0, 13, 9, 559, 5, 0.000820632, 112.97937, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [11, 0, 13, 9, 559, 5, 0.000820632, 112.52063, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [12, 0, 14, 9, 1000, 5, 0.000820632, 111.88095, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [13, 0, 15, 9, 1000, 5, 0.000820632, 111.06032, 0.5, 0.5, 0.050000001, 1, 1, 0],
    [14, 0, 21, 9, 1000, 5, 0.00094582, 108.95569, 0.5, 0.5, 0.050000001, 1, 1, 0],
    [15, 0, 22, 9, 750, 5, 0.00094582, 108.1281, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [16, 0, 22, 10, 500, 5, 0.00094582, 107.53696, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [17, 0, 22, 11, 1000, 5, 0.00094582, 106.82759, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [18, 0, 22, 12, 1000, 5, 0.00094582, 105.88177, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [19, 0, 22, 13, 1000, 5, 0.00094582, 104.93595, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [20, 0, 22, 14, 1000, 5, 0.00094582, 103.99014, 0.5, 0.5, 0.050000001, 2, 1, 0],
    [21, 0, 22, 15, 1000, 5, 0.00094582, 103.04431, 0.5, 0.5, 0.050000001, 1, 1, 0],
]

_SFR_CONN = [
    [0, -1],
    [1, 0, -2],
    [2, 1, -3],
    [3, 2, -4],
    [4, 3, -5],
    [5, 4, -6],
    [6, 5, -7],
    [7, 6],
    [8, -9],
    [9, 8, -10],
    [10, 9, -11],
    [11, 10, -12],
    [12, 11, -13],
    [13, 12],
    [14, -15],
    [15, 14, -16],
    [16, 15, -17],
    [17, 16, -18],
    [18, 17, -19],
    [19, 18, -20],
    [20, 19, -21],
    [21, 20],
]

_SFR_SPD = [[0, "inflow", 691200.0]]

# The published MVR period block the HMP-built records must reproduce verbatim.
_PUBLISHED_MVR_SPD = [
    ["SFR-1", 7, "LAK-1", 0, "FACTOR", 1.0],
    ["LAK-1", 0, "SFR-1", 8, "FACTOR", 1.0],
    ["SFR-1", 13, "LAK-1", 1, "FACTOR", 1.0],
    ["LAK-1", 1, "SFR-1", 14, "FACTOR", 0.5],
]

_NOUTER, _NINNER = 500, 100
_HCLOSE, _RCLOSE = 1e-9, 1e-6


@dataclass(frozen=True)
class SfrLakMvrScenario:
    """Outputs of one p02 run driven through the HMP MVR seam."""

    mvr_rows: list[list[object]]
    maxpackages: int
    lake1_final_stage_ft: float
    lake2_final_stage_ft: float
    transfers_cfd: dict[str, float]
    budget_percent_discrepancy: float


def hmp_mover_records() -> list[MoverRecord]:
    """The four published transfers expressed as HMP MoverRecord instances."""
    return [
        MoverRecord(provider="SFR-1", provider_id=7, receiver="LAK-1", receiver_id=0),
        MoverRecord(provider="LAK-1", provider_id=0, receiver="SFR-1", receiver_id=8),
        MoverRecord(provider="SFR-1", provider_id=13, receiver="LAK-1", receiver_id=1),
        MoverRecord(provider="LAK-1", provider_id=1, receiver="SFR-1", receiver_id=14, value=0.5),
    ]


def load_tolerances() -> dict:
    with (_CASE_DIR / "tolerances.toml").open("rb") as fh:
        return tomllib.load(fh)


def _lake_map() -> np.ndarray:
    lake_map = np.ones((_NLAY, _NROW, _NCOL), dtype=int) * -1
    lake_map[0, :, :] = np.loadtxt(_CASE_DIR / "data" / "lakes-01.txt", dtype=int) - 1
    lake_map[1, :, :] = np.loadtxt(_CASE_DIR / "data" / "lakes-02.txt", dtype=int) - 1
    return lake_map


def _evt_surface(lake_map: np.ndarray) -> np.ndarray:
    s1d = _H1 * np.ones(_NCOL, dtype=float)
    for idx in range(1, _NCOL):
        s1d[idx] = s1d[idx - 1] - (_H1 - _H2) / float(_NCOL - 1)
    surf = np.tile(s1d, (_NROW, 1))
    surf[lake_map[0, :, :] > -1] = _BOTM[0] - 2
    surf[lake_map[1, :, :] > -1] = _BOTM[1] - 2
    return surf


def run_sfr_lak_mvr_scenario(*, workspace: Path) -> SfrLakMvrScenario:
    """Build, run and post-process the p02 model in ``workspace``."""
    import flopy

    records = hmp_mover_records()
    mvr_rows = build_mvr_period_records(records)
    maxpackages = mover_package_count(mvr_rows)
    packages = sorted({(str(row[0]),) for row in mvr_rows} | {(str(row[2]),) for row in mvr_rows})

    lake_map = _lake_map()
    surf = _evt_surface(lake_map)
    chd_spd = []
    for k in range(_NLAY):
        chd_spd += [[k, i, 0, _H1] for i in range(_NROW)]
        chd_spd += [[k, i, _NCOL - 1, _H2] for i in range(_NROW)]

    exe = str(ensure_solver_binary("mf6"))
    sim = flopy.mf6.MFSimulation(sim_name=_SIM_NAME, sim_ws=str(workspace), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, nper=_NPER, perioddata=_TDIS_DS, time_units="days")
    flopy.mf6.ModflowIms(
        sim,
        print_option="summary",
        linear_acceleration="bicgstab",
        outer_maximum=_NOUTER,
        outer_dvclose=_HCLOSE,
        inner_maximum=_NINNER,
        inner_dvclose=_HCLOSE,
        rcloserecord=f"{_RCLOSE} strict",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname=_SIM_NAME, newtonoptions="newton", save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf,
        length_units="feet",
        nlay=_NLAY,
        nrow=_NROW,
        ncol=_NCOL,
        delr=_DELR,
        delc=_DELC,
        idomain=np.ones((_NLAY, _NROW, _NCOL), dtype=int),
        top=_TOP,
        botm=_BOTM,
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=_K11, k33=_K33, save_specific_discharge=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=_SY, ss=_SS)
    flopy.mf6.ModflowGwfic(gwf, strt=_STRT)
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd)
    flopy.mf6.ModflowGwfrcha(gwf, recharge=_RECHARGE)
    flopy.mf6.ModflowGwfevta(gwf, surface=surf, rate=_ETVRATE, depth=_ETVDEPTH)

    idomain_wlakes, pakdata_dict, lak_conn = flopy.mf6.utils.get_lak_connections(
        gwf.modelgrid, lake_map, bedleak=_LAK_BEDLEAK
    )
    lak_packagedata = [[key, _LAK_STRT, pakdata_dict[key]] for key in pakdata_dict]
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK-1",
        time_conversion=86400.0,
        length_conversion=3.28081,
        mover=True,
        print_stage=True,
        nlakes=2,
        noutlets=len(_LAK_OUTLETS),
        packagedata=lak_packagedata,
        connectiondata=lak_conn,
        outlets=_LAK_OUTLETS,
        perioddata=_LAK_SPD,
    )
    lak.obs.initialize(
        filename=f"{_SIM_NAME}.lak.obs",
        digits=10,
        print_input=False,
        continuous={
            f"{_SIM_NAME}.lak.obs.csv": [
                ("lake1", "stage", (0,)),
                ("lake2", "stage", (1,)),
            ]
        },
    )
    gwf.dis.idomain = idomain_wlakes

    sfr = flopy.mf6.ModflowGwfsfr(
        gwf,
        pname="SFR-1",
        time_conversion=86400.0,
        length_conversion=3.28081,
        mover=True,
        nreaches=len(_SFR_PAKDATA),
        packagedata=_SFR_PAKDATA,
        connectiondata=_SFR_CONN,
        perioddata=_SFR_SPD,
    )
    sfr.obs.initialize(
        filename=f"{_SIM_NAME}.sfr.obs",
        digits=10,
        print_input=False,
        continuous={
            f"{_SIM_NAME}.sfr.obs.csv": [
                ("r7_to_mvr", "to-mvr", (7,)),
                ("r8_from_mvr", "from-mvr", (8,)),
                ("r13_to_mvr", "to-mvr", (13,)),
                ("r14_from_mvr", "from-mvr", (14,)),
            ]
        },
    )

    flopy.mf6.ModflowGwfmvr(
        gwf,
        maxmvr=len(mvr_rows),
        maxpackages=maxpackages,
        packages=packages,
        perioddata=mvr_rows,
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{_SIM_NAME}.hds",
        budget_filerecord=f"{_SIM_NAME}.cbc",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
    )
    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    if not success:
        raise RuntimeError("ex-gwf-lak-p02 reproduction did not converge")

    with (workspace / f"{_SIM_NAME}.lak.obs.csv").open(encoding="utf-8") as fh:
        lak_last = {k.upper(): float(v) for k, v in list(csv.DictReader(fh))[-1].items()}
    with (workspace / f"{_SIM_NAME}.sfr.obs.csv").open(encoding="utf-8") as fh:
        sfr_last = {k.upper(): float(v) for k, v in list(csv.DictReader(fh))[-1].items()}

    discrepancy = _last_percent_discrepancy(workspace)
    return SfrLakMvrScenario(
        mvr_rows=mvr_rows,
        maxpackages=maxpackages,
        lake1_final_stage_ft=lak_last["LAKE1"],
        lake2_final_stage_ft=lak_last["LAKE2"],
        transfers_cfd={
            "sfr7_to_lak1": abs(sfr_last["R7_TO_MVR"]),
            "lak1_to_sfr8": abs(sfr_last["R8_FROM_MVR"]),
            "sfr13_to_lak2": abs(sfr_last["R13_TO_MVR"]),
            "lak2_to_sfr14": abs(sfr_last["R14_FROM_MVR"]),
        },
        budget_percent_discrepancy=0.0 if discrepancy is None else float(discrepancy),
    )


PUBLISHED_MVR_SPD = _PUBLISHED_MVR_SPD
