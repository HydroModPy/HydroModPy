"""Same-solver steady-state initial-condition support for MODFLOW 6."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import flopy
import numpy as np

from hydromodpy.core.time.steady_initialization import (
    single_period_mean_forcing_time_grid,
)
from hydromodpy.solver.modflow_common import ModflowPreprocessOptions, ModflowRunOptions
from hydromodpy.solver.steady_initial_conditions import (
    flow_uses_steady_state_initial_condition,
    steady_flow_copy_for_initialization,
)

_STEADY_INIT_DVCLOSE_MIN = 1e-3
_STEADY_INIT_MAXIMUM_MIN = 1000
_STEADY_INIT_PERCENT_DISCREPANCY_TOL = 0.1
_PERCENT_DISCREPANCY_RE = re.compile(r"PERCENT\s+DISCREPANCY\s*=\s*([-+0-9.Ee]+)")


def _modflow_config_for_steady_initialization(model: object) -> object:
    config = getattr(model, "modflow_config", None)
    runtime = getattr(config, "runtime", None)
    if config is None or runtime is None:
        return config
    if not hasattr(config, "model_copy") or not hasattr(runtime, "model_copy"):
        return config
    # The auxiliary steady solve only materializes an initial condition. A
    # millimetric closure avoids rejecting physically balanced starts that do
    # not satisfy the stricter transient-run tolerance.
    runtime_copy = runtime.model_copy(
        update={
            "mf6_executable_name": str(model.exe),
            "mf6_outer_dvclose": max(
                float(getattr(runtime, "mf6_outer_dvclose", _STEADY_INIT_DVCLOSE_MIN)),
                _STEADY_INIT_DVCLOSE_MIN,
            ),
            "mf6_inner_dvclose": max(
                float(getattr(runtime, "mf6_inner_dvclose", _STEADY_INIT_DVCLOSE_MIN)),
                _STEADY_INIT_DVCLOSE_MIN,
            ),
            "mf6_outer_maximum": max(
                int(getattr(runtime, "mf6_outer_maximum", _STEADY_INIT_MAXIMUM_MIN)),
                _STEADY_INIT_MAXIMUM_MIN,
            ),
            "mf6_inner_maximum": max(
                int(getattr(runtime, "mf6_inner_maximum", _STEADY_INIT_MAXIMUM_MIN)),
                _STEADY_INIT_MAXIMUM_MIN,
            ),
            "mf6_newton": True,
            "mf6_newton_under_relaxation": True,
            # The auxiliary solve forces Newton, which MF6 forbids with NPF
            # rewetting. Disable rewet here so a user-valid newton=False +
            # rewet=True transient config does not trip the NEWTON+REWET guard
            # during steady spin-up.
            "mf6_enable_rewet": False,
            # Forcing Newton also makes the Jacobian non-symmetric, so a
            # user-valid newton=False + linear_acceleration='CG' config must not
            # inherit CG here (it would trip the NEWTON+CG guard). Force BICGSTAB.
            "mf6_linear_acceleration": "BICGSTAB",
        }
    )
    return config.model_copy(update={"runtime": runtime_copy})


def _read_final_head(head_path: Path, *, nlay: int, ncpl: int) -> np.ndarray:
    head_file = flopy.utils.HeadFile(str(head_path))
    try:
        times = head_file.get_times()
        if not times:
            raise RuntimeError(f"No head times were written by steady initialization: {head_path}")
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


def _read_final_percent_discrepancy(list_path: Path) -> float | None:
    if not list_path.is_file():
        return None
    last_value: float | None = None
    for line in list_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = _PERCENT_DISCREPANCY_RE.search(line)
        if match is None:
            continue
        try:
            last_value = float(match.group(1))
        except ValueError:
            continue
    return last_value


def _steady_initialization_balance_is_acceptable(list_path: Path) -> bool:
    discrepancy = _read_final_percent_discrepancy(list_path)
    return discrepancy is not None and abs(discrepancy) <= _STEADY_INIT_PERCENT_DISCREPANCY_TOL


def run_modflow6_steady_state_initialization(model: object, *, verbose: bool) -> np.ndarray:
    """Run one auxiliary steady MF6 model and return heads for the transient IC."""
    # Keep the auxiliary workspace short. On Windows, MF6 still fails on long
    # nested paths when writing DISV binary grid files.
    init_root = Path(str(model.full_path)) / "_ssic"
    init_name = "ssic"
    steady_model = model.__class__(
        geographic=model.geographic,
        modflow_config=_modflow_config_for_steady_initialization(model),
        model_folder=str(init_root),
        model_name=init_name,
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
        mesh_planar=getattr(model, "runtime_mesh_planar", None),
        mesh_support=getattr(model, "runtime_mesh_support", None),
        flow_runtime_overrides=getattr(model, "_flow_runtime_overrides", None),
    )
    success = steady_model.processing(
        ModflowRunOptions(write_model=True, run_model=True, verbose=bool(verbose))
    )

    output_name = str(getattr(steady_model, "model_output_name", steady_model.model_name))
    head_path = Path(str(steady_model.full_path)) / f"{output_name}.hds"
    list_path = Path(str(steady_model.full_path)) / f"{output_name}.lst"
    if not success:
        if not _steady_initialization_balance_is_acceptable(list_path):
            raise RuntimeError("MODFLOW 6 steady-state initial-condition solve failed.")
        warnings.warn(
            "MODFLOW 6 steady-state initial-condition solve did not satisfy "
            "solver convergence, but the final water budget is closed; using "
            "the final balanced heads as transient initial conditions.",
            RuntimeWarning,
            stacklevel=2,
        )
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


def apply_modflow6_steady_state_initial_heads(model: object, head_m: np.ndarray) -> None:
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
