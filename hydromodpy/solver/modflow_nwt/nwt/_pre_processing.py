"""FLOPY package assembly from solver-ready ``FlowModflowInputs``.

Splits the heavy ``ModflowNwt.pre_processing`` body into a free
function that mutates the solver instance in place. The solver class
stays a thin lifecycle facade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import flopy
import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions

from ._progress import ITMUNI_TO_SECONDS, scale_rate_payload
from .diagnostics import check_water_flow_connectivity
from .flow_to_modflow_adapter import FlowModflowInputs

if TYPE_CHECKING:
    from .nwt_solver import ModflowNwt

logger = get_logger(__name__)


def assemble_flopy_packages(
    solver: ModflowNwt,
    flow_inputs: FlowModflowInputs,
    active_options: ModflowPreprocessOptions,
) -> None:
    """Assemble FLOPY packages on ``solver.mf`` from solver-ready payloads.

    Mutates ``solver`` in place: sets the ``bas``, ``upw``, ``rch``, ``evt``,
    ``drn``, ``wel``, ``oc``, ``chd`` attributes plus auxiliary state
    (``hk``, ``sy``, ``ss``, ``laytype``, ``laywet``, ``recharge``,
    ``drain_array``, ``prob_cells``).
    """
    si_to_solver = ITMUNI_TO_SECONDS.get(solver.dis_itmuni, 1.0)

    solver.drain_array = flow_inputs.drain_array

    if flow_inputs.chd_spd is not None:
        solver.chd = flopy.modflow.ModflowChd(solver.mf, stress_period_data=flow_inputs.chd_spd)

    # BAS contract reminder:
    # - ibound > 0: active cells (head is solved)
    # - ibound = 0: inactive/no-flow cells
    # - ibound < 0: constant-head cells
    # - strt: startup head field and imposed head on constant-head cells
    solver.bas_hnoflo = solver._params.runtime.bas_hnoflo
    solver.bas = flopy.modflow.ModflowBas(
        solver.mf,
        ibound=flow_inputs.ibound,
        strt=flow_inputs.strt,
        hnoflo=solver.bas_hnoflo,
    )

    solver.laywet = np.zeros(solver.nlay)
    solver.laytype = np.ones(solver.nlay)

    solver.hk = flow_inputs.hk * si_to_solver
    solver.hk_value = flow_inputs.hk_value * si_to_solver
    solver.sy = flow_inputs.sy
    solver.sy_value = flow_inputs.sy_value
    solver.ss = flow_inputs.ss
    solver.ss_value = flow_inputs.ss_value

    solver.upw_hdry = solver._params.runtime.upw_hdry
    solver.upw = flopy.modflow.ModflowUpw(
        solver.mf,
        laytyp=solver.laytype,
        laywet=solver.laywet,
        hk=solver.hk,
        sy=solver.sy,
        ss=solver.ss,
        vka=solver._params.process_specific.vka,
        iphdry=solver._params.runtime.upw_iphdry,
        hdry=solver.upw_hdry,
        layvka=solver._params.runtime.upw_layvka,
        extension="upw",
        unitnumber=None,
        noparcheck=False,
    )

    # Recharge / EVT rates arrive in SI (m/s) but MODFLOW interprets
    # them according to itmuni; apply the same SI to solver-time scaling
    # already used for K and drain conductance.
    rch_data_solver = scale_rate_payload(flow_inputs.rch_data, si_to_solver)
    evt_spd_solver = scale_rate_payload(flow_inputs.evt_spd, si_to_solver)

    if evt_spd_solver is not None:
        # Position the EVT extraction surface a configurable distance
        # below topography (legacy default = top - 2 m) and let the
        # extinction depth come from the FlowEtpConfig too.
        surf_offset = float(getattr(flow_inputs, "evt_surface_offset", 2.0))
        exdp = float(getattr(flow_inputs, "evt_extinction_depth", 1.0))
        solver.evt = flopy.modflow.ModflowEvt(
            solver.mf,
            evtr=evt_spd_solver,
            surf=solver.top_elevation - surf_offset,
            nevtop=solver._params.runtime.evt_nevtop,
            exdp=exdp,
            ievt=solver._params.runtime.evt_ievt,
            ipakcb=solver._params.runtime.evt_ipakcb,
        )

    if rch_data_solver is not None:
        solver.rch = flopy.modflow.ModflowRch(solver.mf, rech=rch_data_solver)
    # Store the processed RCH schedule so post-processing can read it
    # back without going through the flow object. Format: dict
    # {kper: rate [L/T]} in solver time units, mirroring what was fed
    # to ModflowRch. None when recharge is not active.
    solver.recharge = rch_data_solver

    # DRN is applied to all the surface of the model: enables seepage on the top layer
    if flow_inputs.drn_spd is not None:
        # Drainage conductance [L^2/T] was derived from hk in SI;
        # convert to solver time units (column index 4 = conductance).
        for kper_data in flow_inputs.drn_spd.values():
            kper_data[:, 4] *= si_to_solver
        solver.drn = flopy.modflow.ModflowDrn(
            solver.mf,
            stress_period_data=flow_inputs.drn_spd,
        )

    if flow_inputs.wel_spd:
        # Well flux is built in SI (m3/s); MODFLOW expects volume per
        # solver time-step. Scale the 4th column (flux) per row.
        wel_spd_solver = {
            kper: [list(row[:3]) + [float(row[3]) * si_to_solver] for row in rows]
            for kper, rows in flow_inputs.wel_spd.items()
        }
        solver.wel = flopy.modflow.ModflowWel(
            solver.mf,
            ipakcb=solver._params.runtime.wel_ipakcb,
            stress_period_data=wel_spd_solver,
        )

    stress_period_data: dict[tuple[int, int], list[str]] = {}
    for kper in range(solver.nper):
        kstp = int(solver.nstp[kper])
        if kstp > 1:
            for ts in range(kstp):
                stress_period_data[(kper, ts)] = ["save head", "save budget"]
        else:
            stress_period_data[(kper, 0)] = ["save head", "save budget"]
    solver.oc = flopy.modflow.ModflowOc(
        solver.mf,
        stress_period_data=stress_period_data,
        extension=["oc", "hds", "cbc"],
        unitnumber=None,
        compact=solver._params.runtime.oc_compact,
    )
    solver.oc.reset_budgetunit(fname=solver.model_name + ".cbc")

    if active_options.check_grid:
        grid_to_check = solver.mf.modelgrid.top_botm
        problematic_cells = check_water_flow_connectivity(grid_to_check)
        if not problematic_cells:
            logger.info("MODFLOW grid connectivity check passed")
            solver.prob_cells = 0
        else:
            logger.warning(
                "MODFLOW grid connectivity check found %d problematic cells",
                len(problematic_cells),
            )
            solver.prob_cells = len(problematic_cells)


__all__ = ["assemble_flopy_packages"]
