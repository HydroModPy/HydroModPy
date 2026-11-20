"""Same-solver steady-state initial-condition support for MODFLOW-NWT.

The auxiliary solve runs on ``steady_variant`` of the model of the run, which
starts from the top. Its final head is set in the BAS package of the main
model, so the transient run starts from the steady state.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import flopy
import numpy as np

from hydromodpy.core.console import progress
from hydromodpy.model.model import steady_variant
from hydromodpy.solver.modflow_common.options import ModflowRunOptions


def _read_final_head(head_path: Path, *, nlay: int, nrow: int, ncol: int) -> np.ndarray:
    head_file = flopy.utils.HeadFile(str(head_path), precision="single")
    try:
        times = head_file.get_times()
        if not times:
            raise RuntimeError(f"No head times were written by steady initialization: {head_path}")
        raw = np.asarray(head_file.get_data(totim=times[-1]), dtype=float)
    finally:
        head_file.close()

    try:
        head = raw.reshape(int(nlay), int(nrow), int(ncol))
    except ValueError as exc:
        raise ValueError(
            "Steady initialization head array shape mismatch: "
            f"{raw.shape} vs expected {(int(nlay), int(nrow), int(ncol))}."
        ) from exc
    return np.asarray(head, dtype=float)


def run_nwt_steady_state_initialization(model: object) -> np.ndarray:
    """Run one auxiliary steady NWT model and return heads for transient BAS.

    ``model`` is the ``ModflowNwt`` of the run, built from its ``inputs``. The
    auxiliary solver keeps its options (the drain band, the sink fill, the
    grid check) and takes the one-period time grid of the steady variant.
    """
    steady_inputs = steady_variant(model.inputs)
    init_root = Path(str(model.full_path)) / "_steady_state_initialization"
    init_name = f"{model.model_name}_steady_ic"
    steady_model = model.__class__(
        modflow_config=model.modflow_config,
        model_folder=str(init_root),
        model_name=init_name,
        bin_path=str(Path(str(model.exe)).parent),
        preprocess_options=replace(model.preprocess_options, time_grid=steady_inputs.time.grid),
    )
    steady_model.auxiliary = True
    steady_model.pre_processing(steady_inputs)
    # Auxiliary single-period solve: keep it out of the live display.
    with progress.suppressed():
        success = steady_model.processing(ModflowRunOptions(write_model=True, run_model=True))
    if not success:
        raise RuntimeError("MODFLOW-NWT steady-state initial-condition solve failed.")

    head_path = Path(str(steady_model.full_path)) / f"{steady_model.model_name}.hds"
    head = _read_final_head(
        head_path,
        nlay=int(model.nlay),
        nrow=int(model.nrow),
        ncol=int(model.ncol),
    )
    artifact_path = Path(str(model.full_path)) / "_steady_state_initial_conditions.npz"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        artifact_path,
        head_m=head,
        solver=np.asarray(["modflow_nwt"]),
        source=np.asarray(["flow.ic.steady_state"]),
    )
    return head


def apply_nwt_steady_state_initial_heads(model: object, head_m: np.ndarray) -> None:
    """Inject materialized steady heads into the already-built BAS package."""
    head = np.asarray(head_m, dtype=float).reshape(
        int(model.nlay), int(model.nrow), int(model.ncol)
    )
    model.bas.strt = head.copy()
    model._steady_state_initial_heads_m = head.copy()
    model._steady_state_initialization_solver = "modflow_nwt"


__all__ = [
    "apply_nwt_steady_state_initial_heads",
    "run_nwt_steady_state_initialization",
]
