"""Same-solver steady-state initial-condition support for MODFLOW 6."""

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


def _modflow_config_with_same_executable(model: object) -> object:
    config = getattr(model, "modflow_config", None)
    runtime = getattr(config, "runtime", None)
    if config is None or runtime is None:
        return config
    if not hasattr(config, "model_copy") or not hasattr(runtime, "model_copy"):
        return config
    runtime_copy = runtime.model_copy(update={"mf6_executable_name": str(model.exe)})
    return config.model_copy(update={"runtime": runtime_copy})


def _read_final_head(head_path: Path, *, nlay: int, ncpl: int) -> np.ndarray:
    head_file = flopy.utils.HeadFile(str(head_path))
    try:
        times = head_file.get_times()
        if not times:
            raise RuntimeError(
                f"No head times were written by steady initialization: {head_path}"
            )
        raw = np.asarray(head_file.get_data(totim=times[-1]), dtype=float)
    finally:
        head_file.close()

    if raw.ndim == 3:
        raw = raw.reshape(int(nlay), -1)
    elif raw.ndim == 2:
        raw = raw.reshape(int(nlay), -1)
    else:
        raise ValueError(
            f"Steady initialization head array must be 2D or 3D; got shape {raw.shape}."
        )
    if raw.shape != (int(nlay), int(ncpl)):
        raise ValueError(
            "Steady initialization head array shape mismatch: "
            f"{raw.shape} vs expected {(int(nlay), int(ncpl))}."
        )
    return np.asarray(raw, dtype=float)


def run_modflow6_steady_state_initialization(
    model: object, *, verbose: bool
) -> np.ndarray:
    """Run one auxiliary steady MF6 model and return heads for the transient IC."""
    init_root = Path(str(model.full_path)) / "_steady_state_initialization"
    init_name = f"{model.model_name}_steady_ic"
    steady_model = model.__class__(
        geographic=model.geographic,
        modflow_config=_modflow_config_with_same_executable(model),
        model_folder=str(init_root),
        model_name=init_name,
        preprocess_options=ModflowPreprocessOptions(
            box=bool(getattr(model.preprocess_options, "box", True)),
            sink_fill=bool(getattr(model.preprocess_options, "sink_fill", False)),
            check_grid=bool(getattr(model.preprocess_options, "check_grid", True)),
            time_grid=single_period_mean_forcing_time_grid(
                getattr(model, "time_grid", None)
            ),
        ),
    )
    steady_model.pre_processing(
        flow=steady_flow_copy_for_initialization(model.flow),
        domain=model.domain,
        mesh_planar=getattr(model, "runtime_mesh_planar", None),
        mesh_support=getattr(model, "runtime_mesh_support", None),
        flow_runtime_overrides=getattr(model, "_flow_runtime_overrides", None),
    )
    success = steady_model.processing(
        ModflowRunOptions(write_model=True, run_model=True, verbose=bool(verbose))
    )
    if not success:
        raise RuntimeError("MODFLOW 6 steady-state initial-condition solve failed.")

    head_path = Path(str(steady_model.full_path)) / f"{steady_model.model_name}.hds"
    head = _read_final_head(head_path, nlay=int(model.nlay), ncpl=int(model.ncpl))
    artifact_path = Path(str(model.full_path)) / "_steady_state_initial_conditions.npz"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        artifact_path,
        head_m=head,
        solver=np.asarray(["modflow6"]),
        source=np.asarray(["flow.ic.steady_state"]),
    )
    return head


def apply_modflow6_steady_state_initial_heads(
    model: object, head_m: np.ndarray
) -> None:
    """Inject materialized steady heads into the already-built MF6 IC package."""
    head = np.asarray(head_m, dtype=float).reshape(int(model.nlay), int(model.ncpl))
    model.ic.strt.set_data(head)
    model._steady_state_initial_heads_m = head.copy()
    model._steady_state_initialization_solver = "modflow6"


__all__ = [
    "apply_modflow6_steady_state_initial_heads",
    "flow_uses_steady_state_initial_condition",
    "run_modflow6_steady_state_initialization",
]
