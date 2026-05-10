"""Same-solver steady-state initial-condition support for MODFLOW-NWT."""

from __future__ import annotations

from pathlib import Path

import flopy
import numpy as np

from hydromodpy.solver.modflow_common import ModflowPreprocessOptions, ModflowRunOptions
from hydromodpy.solver.steady_initial_conditions import (
    flow_uses_steady_state_initial_condition,
    steady_flow_copy_for_initialization,
)
from hydromodpy.solver.utils.temporal.steady_initialization import (
    single_period_mean_forcing_time_grid,
)


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


def run_nwt_steady_state_initialization(model: object, *, verbose: bool) -> np.ndarray:
    """Run one auxiliary steady NWT model and return heads for transient BAS."""
    init_root = Path(str(model.full_path)) / "_steady_state_initialization"
    init_name = f"{model.model_name}_steady_ic"
    steady_model = model.__class__(
        geographic=model.geographic,
        modflow_config=model.modflow_config,
        model_folder=str(init_root),
        model_name=init_name,
        bin_path=str(Path(str(model.exe)).parent),
        preprocess_options=ModflowPreprocessOptions(
            box=bool(getattr(model.preprocess_options, "box", True)),
            sink_fill=bool(getattr(model.preprocess_options, "sink_fill", False)),
            check_grid=bool(getattr(model.preprocess_options, "check_grid", True)),
            time_grid=single_period_mean_forcing_time_grid(getattr(model, "time_grid", None)),
        ),
    )
    steady_model.pre_processing(
        flow=steady_flow_copy_for_initialization(model.flow),
        domain=model.domain,
        flow_runtime_overrides=getattr(model, "flow_runtime_overrides", None),
    )
    success = steady_model.processing(
        ModflowRunOptions(write_model=True, run_model=True, verbose=bool(verbose))
    )
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
    "flow_uses_steady_state_initial_condition",
    "run_nwt_steady_state_initialization",
]
