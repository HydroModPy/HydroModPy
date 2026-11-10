"""Same-solver steady-state initial-condition support for MODFLOW 6."""

from __future__ import annotations

import re
import warnings
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import flopy
import numpy as np

from hydromodpy.core.console import progress
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.interrupts import raise_if_stop_requested
from hydromodpy.model.initial.heads import cycles_have_settled
from hydromodpy.model.initial.state import CyclicStart, SolvedState
from hydromodpy.model.model import cycle_variant, steady_variant
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.modflow6.builders.lake import (
    LAK_STAGE_SUFFIX,
    apply_lake_stages,
    lake_ids_in_package_order,
    read_final_lake_stages,
)
from hydromodpy.solver.modflow6.support.names import mf6_safe_name
from hydromodpy.solver.modflow_common import ModflowRunOptions

logger = get_logger(__name__)

_STEADY_INIT_DVCLOSE_MIN = 1e-3
_STEADY_INIT_MAXIMUM_MIN = 1000
_STEADY_INIT_PERCENT_DISCREPANCY_TOL = 0.1
_PERCENT_DISCREPANCY_RE = re.compile(r"PERCENT\s+DISCREPANCY\s*=\s*([-+0-9.Ee]+)")

STEADY_FOLDER = "_ssic"
"""The folder of the auxiliary steady solve, inside the folder of the run."""

CYCLE_FOLDER_PREFIX = "_cyc"
"""The folder of spin-up cycle ``n`` is ``_cyc<n>``, inside the folder of the run."""


def is_auxiliary_folder(name: str) -> bool:
    """Whether a folder of the run holds an auxiliary model, the steady solve or a cycle."""
    if name == STEADY_FOLDER:
        return True
    suffix = name.removeprefix(CYCLE_FOLDER_PREFIX)
    return suffix != name and suffix.isdigit()


def auxiliary_slot(model: object, folder: Path, name: str) -> RunSlot:
    """The slot of an auxiliary model, derived from the slot of the run.

    The auxiliary model solves in ``folder / name``, with the binaries and the
    shared forcing folder of the run, so it reads the same recharge files and
    runs the same executable. A run built without a slot gives neither. It
    reads the stop flag of the run, so a stop asked during an auxiliary solve
    ends it between two time steps.
    """
    slot = getattr(model, "slot", None)
    return RunSlot(
        folder=folder,
        name=name,
        bin_dir=None if slot is None else slot.bin_dir,
        shared_forcing_dir=None if slot is None else slot.shared_forcing_dir,
        stop_flag=None if slot is None else slot.stop_flag,
    )


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


def _model_listing_path(model: object) -> Path:
    """Return the listing MF6 wrote for an auxiliary model.

    MF6 names the listing after the model name it was given, which is the safe
    lowercase name, while the head file keeps the output stem. The two differ for a
    name with a capital letter, a space or more than 16 characters.
    """
    safe = getattr(model, "model_name_mf6", None) or mf6_safe_name(str(model.model_name))
    return Path(str(model.full_path)) / f"{safe}.lst"


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
    """Run one auxiliary steady MF6 model and return heads for the transient IC.

    The auxiliary model builds from ``steady_variant`` of the model of the run:
    one period, a steady regime, the run's forcings averaged, and a start from
    the top. The run's own model changes by one attribute only,
    ``initial_state_converged``: ``True`` when the solve converged, ``False`` when
    it did not and its closed budget was accepted. The run hands it to the runner,
    which will not start a transport run behind a ``False``.
    """
    # Keep the auxiliary workspace short. On Windows, MF6 still fails on long
    # nested paths when writing DISV binary grid files.
    slot = auxiliary_slot(model, Path(str(model.full_path)) / STEADY_FOLDER, "ssic")
    steady_inputs = steady_variant(model.inputs)
    steady_model = model.__class__(
        modflow_config=_modflow_config_for_steady_initialization(model),
        model_folder=str(slot.folder),
        model_name=slot.name,
        bin_path=slot.bin_dir,
        preprocess_options=replace(model.preprocess_options, time_grid=steady_inputs.time.grid),
    )
    steady_model.auxiliary = True
    steady_model.pre_processing(steady_inputs, slot=slot)
    # Auxiliary single-period solve: keep it out of the live display.
    with progress.suppressed():
        success = steady_model.processing(
            ModflowRunOptions(write_model=True, run_model=True, verbose=bool(verbose))
        )

    output_name = str(getattr(steady_model, "model_output_name", steady_model.model_name))
    head_path = Path(str(steady_model.full_path)) / f"{output_name}.hds"
    list_path = _model_listing_path(steady_model)
    model.initial_state_converged = bool(success)
    if not success:
        if not _steady_initialization_balance_is_acceptable(list_path):
            raise RuntimeError("MODFLOW 6 steady-state initial-condition solve failed.")
        message = (
            "MODFLOW 6 steady-state initial-condition solve did not satisfy "
            "solver convergence, but the final water budget is closed; using "
            "the final balanced heads as transient initial conditions."
        )
        logger.warning(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)
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


def run_modflow6_cyclic_spinup(model: object, *, verbose: bool) -> tuple[np.ndarray, int, bool]:
    """Repeat the run's own period until its head field stops moving.

    Returns the last cycle's heads, how many cycles ran, and whether the loop
    settled. A loop that ran out of cycles still returns its last state, and the
    caller says so: chaining a production run from a state that did not settle is
    reported rather than assumed, the same rule ``hmp spinup`` already follows.

    Each cycle is an auxiliary model in its own folder, built exactly as the steady
    initialization is, so this works inside a lightweight calibration trial: the
    cycles never touch the run's store.

    A lake starts each cycle at the stage the cycle before ended on, as the head
    does, and the loop settles only when the lake stages have stopped moving too,
    at the same tolerance as the heads. The stop flag of the run is read between
    two cycles.
    """
    initial = model.inputs.initial
    if not isinstance(initial, CyclicStart):
        raise ValueError("run_modflow6_cyclic_spinup called on a model that does not ask for it")
    strategy = initial.strategy

    seed: np.ndarray | None = None
    if strategy.first_cycle_from == "steady_state":
        seed = run_modflow6_steady_state_initialization(model, verbose=verbose)
        # A seed is not the start of the run: the cycles that follow settle the state.
        model.initial_state_converged = None

    stop_flag = getattr(getattr(model, "slot", None), "stop_flag", None)
    previous: np.ndarray | None = None
    previous_stages: Mapping[str, float] = {}
    stages: Mapping[str, float] = {}
    head: np.ndarray | None = None
    settled = False
    cycles = 0
    for cycle in range(int(strategy.max_cycles)):
        raise_if_stop_requested(stop_flag)
        head = _run_one_spinup_cycle(
            model, cycle=cycle, seed=seed, seed_lake_stages=stages, verbose=verbose
        )
        stages = cycle_lake_stages(model, cycle)
        cycles = cycle + 1
        if cycles_have_settled(
            previous,
            head,
            tol_head_m=strategy.tol_head_m,
            previous_stages=previous_stages,
            current_stages=stages,
        ):
            settled = True
            break
        previous, previous_stages = head, stages
        seed = head
    assert head is not None  # max_cycles >= 1, so the loop body ran
    return head, cycles, settled


def cycle_lake_stages(model: object, cycle: int) -> dict[str, float]:
    """The stage of each lake at the end of spin-up cycle ``cycle`` of ``model``, ``{}`` without a lake.

    They are read from the stage file the cycle wrote, in double precision. The
    cycles and the run share their lakes, so the order of the records is the
    order of the lakes of ``model``.
    """
    lake_ids = lake_ids_in_package_order(model)
    if not lake_ids:
        return {}
    folder = Path(str(model.full_path)) / f"{CYCLE_FOLDER_PREFIX}{cycle}"
    files = sorted(folder.rglob(f"*{LAK_STAGE_SUFFIX}"))
    if len(files) != 1:
        raise FileNotFoundError(
            f"Spin-up cycle {cycle} should leave one lake stage file under {folder}, "
            f"found {len(files)}."
        )
    stages = read_final_lake_stages(files[0], lake_ids)
    assert stages is not None  # the file exists
    return stages


def _run_one_spinup_cycle(
    model: object,
    *,
    cycle: int,
    seed: np.ndarray | None,
    seed_lake_stages: Mapping[str, float] = MappingProxyType({}),
    verbose: bool,
) -> np.ndarray:
    """Run one cycle over the run's own period and return the heads it ended on.

    The cycle starts from ``seed``, with its lakes at ``seed_lake_stages``.
    """
    slot = auxiliary_slot(
        model, Path(str(model.full_path)) / f"{CYCLE_FOLDER_PREFIX}{cycle}", f"cyc{cycle}"
    )
    # The cycle starts where the previous one ended, set as it is in the IC package.
    start = (
        None
        if seed is None
        else SolvedState(head=seed, solver="modflow6", lake_stages=seed_lake_stages)
    )
    cycle_model = model.__class__(
        modflow_config=_modflow_config_for_steady_initialization(model),
        model_folder=str(slot.folder),
        model_name=slot.name,
        bin_path=slot.bin_dir,
        preprocess_options=model.preprocess_options,
    )
    cycle_model.auxiliary = True
    cycle_model.pre_processing(cycle_variant(model.inputs, start), slot=slot)
    with progress.suppressed():
        success = cycle_model.processing(
            ModflowRunOptions(write_model=True, run_model=True, verbose=bool(verbose))
        )
    output_name = str(getattr(cycle_model, "model_output_name", cycle_model.model_name))
    head_path = Path(str(cycle_model.full_path)) / f"{output_name}.hds"
    list_path = _model_listing_path(cycle_model)
    if not success and not _steady_initialization_balance_is_acceptable(list_path):
        raise RuntimeError(
            f"MODFLOW 6 spin-up cycle {cycle} failed to converge and its water budget does "
            "not close, so its final heads are not a state to start anything from."
        )
    return _read_final_head(head_path, nlay=int(model.nlay), ncpl=int(model.ncpl))


def apply_modflow6_cyclic_spinup_heads(model: object, head_m: np.ndarray) -> None:
    """Inject the last cycle's heads into the already-built MF6 IC package."""
    head = np.asarray(head_m, dtype=float).reshape(int(model.nlay), int(model.ncpl))
    model.ic.strt.set_data(head)
    model._cyclic_spinup_initial_heads_m = head.copy()


def apply_modflow6_cyclic_spinup_lakes(model: object, cycles: int) -> None:
    """Start the lakes of the built model at the stages the last of ``cycles`` cycles ended on.

    The run starts from the state of the last cycle, so its lakes do too. A
    model without a lake is left as it is.
    """
    lak = getattr(model, "lak", None)
    if lak is None or not lake_ids_in_package_order(model):
        return
    apply_lake_stages(lak, cycle_lake_stages(model, int(cycles) - 1))


def apply_modflow6_steady_state_initial_heads(model: object, head_m: np.ndarray) -> None:
    """Inject materialized steady heads into the already-built MF6 IC package."""
    head = np.asarray(head_m, dtype=float).reshape(int(model.nlay), int(model.ncpl))
    model.ic.strt.set_data(head)
    model._steady_state_initial_heads_m = head.copy()
    model._steady_state_initialization_solver = "modflow6"


__all__ = [
    "CYCLE_FOLDER_PREFIX",
    "STEADY_FOLDER",
    "apply_modflow6_cyclic_spinup_heads",
    "apply_modflow6_cyclic_spinup_lakes",
    "apply_modflow6_steady_state_initial_heads",
    "auxiliary_slot",
    "cycle_lake_stages",
    "is_auxiliary_folder",
    "run_modflow6_cyclic_spinup",
    "run_modflow6_steady_state_initialization",
]
