"""Phase 'transport': run MT3DMS or MODFLOW 6 transport."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher.run_result import RunResult


def _run_transport(result: "RunResult") -> None:
    from hydromodpy.solver import SolverEngine
    from hydromodpy.solver.modflow_nwt import Mt3dms
    from hydromodpy.solver.modflow6 import Modflow6Transport

    if result.model_modflow is None:
        raise RuntimeError(
            "Phase 'transport' requires 'flow' to have run first "
            "(result.model_modflow is None)."
        )

    cfg           = result.cfg
    ws            = result.workspace
    model_modflow = result.model_modflow
    suffix_name   = "_mt_s1"

    if cfg.solver.solver_engine == SolverEngine.MODFLOW_NWT:
        model_transport = Mt3dms(
            result.domain,
            result.transport,
            model_modflow,
            model_folder=ws.simulations_folder,
            model_name=model_modflow.model_name,
            suffix_name=suffix_name,
            bin_path=ws.bin_path,
        )
    else:
        model_transport = Modflow6Transport(
            result.domain,
            result.transport,
            model_modflow,
            model_folder=ws.simulations_folder,
            model_name=model_modflow.model_name,
            suffix_name=suffix_name,
        )

    model_transport.pre_processing()
    model_transport.processing(write_model=True, run_model=True, verbose=True)
    model_transport.post_processing()

    result.model_transport = model_transport
