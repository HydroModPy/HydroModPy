"""MODFLOW 6 flow solver facade aligned with HydroModPy workflow APIs.

This module exposes the :class:`Modflow6` adapter. Concern-specific helpers
live in ``build`` (pre_processing) and ``run`` (processing).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np

from hydromodpy.catchment.drainage.descent import Descent, DescentBasin
from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.model.model import Model
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.modflow6.api.api_runner import Mf6ApiContext
from hydromodpy.solver.modflow6.build import (
    apply_preprocess_options,
    resolve_xt3d_options,
    run_pre_processing,
    validate_pre_processing_inputs,
    xt3d_mode,
)
from hydromodpy.solver.modflow6.builders.solver_options import (
    resolve_ims_complexity,
    xt3d_is_enabled,
)
from hydromodpy.solver.modflow6.modflow6_config import (
    Modflow6Config,
    _coerce_modflow6_config,
)
from hydromodpy.solver.modflow6.run import run_processing
from hydromodpy.solver.modflow6.support.names import mf6_safe_name
from hydromodpy.solver.modflow_common import (
    ModflowPreprocessOptions,
    ModflowRunOptions,
    SolverRoutingContext,
    ensure_platform_executable,
    ensure_solver_binary,
)
from hydromodpy.solver.modflow_grid import SolverGridContext


class Modflow6:
    """Flow solver based on MODFLOW 6 (GWF)."""

    def __init__(
        self,
        modflow_config: Modflow6Config | Mapping[str, object] | None = None,
        model_folder: str | Path = "HydroModPy_outputs",
        model_name: str = "Default",
        bin_path: str | Path | None = None,
        preprocess_options: ModflowPreprocessOptions | None = None,
    ):
        self.model_folder = model_folder
        if not os.path.exists(self.model_folder):
            create_folder(self.model_folder)

        self.model_name = model_name
        self.model_name_mf6 = mf6_safe_name(model_name)
        self.model_output_name = model_name
        # The frozen Model this solver builds from, bound by pre_processing. It is
        # read and never changed: a build leaves the Model as it found it.
        self.inputs: Model | None = None
        # The slot of the run, bound by pre_processing: its shared forcing folder
        # and its binaries, which an auxiliary solve and a rerun keep.
        self.slot: RunSlot | None = None
        # The input files the last write left, relative to full_path, set by
        # processing. A rerun copies them.
        self.input_files: tuple[str, ...] = ()
        # Whether a downstream MT3DMS run reads the output, set by the adapter.
        self.link_mt3dms = False
        self.last_flow_solve_time_seconds: float | None = None

        self.full_path = os.path.join(model_folder, model_name)
        self.dem_watershed_path = None
        self.grid_ctx: SolverGridContext | None = None
        self.routing_ctx: SolverRoutingContext | None = None
        # The descent D of the build and its basin at the catchment outlet, set by
        # build.run_pre_processing.
        self.descent: Descent | None = None
        self.descent_basin: DescentBasin | None = None
        # The cell below each lake dam ({lake id: cell}), set with D by the build.
        self.dam_foot_cells: dict[str, int] = {}
        # Set by the steady initialization and the spin-up cycles: a model that
        # is never extracted builds D only for its SFR walks and stores none.
        self.auxiliary = False

        self.modflow_config = _coerce_modflow6_config(modflow_config)
        runtime = self.modflow_config.runtime
        exe_name = runtime.mf6_executable_name
        if exe_name and os.path.isabs(exe_name):
            self.exe = str(ensure_platform_executable(exe_name))
        elif not exe_name or exe_name in ("mf6", "mf6.exe"):
            self.exe = str(ensure_solver_binary("mf6", bin_path))
        else:
            self.exe = str(ensure_platform_executable(os.path.join(bin_path, exe_name)))

        self.sink: np.ndarray | None = None

        self.preprocess_options = preprocess_options or ModflowPreprocessOptions()
        self._apply_preprocess_options(self.preprocess_options)
        self._exposed_band_runoff_specs: list | None = None
        self._evt_rate_payload: dict[int, object] | None = None
        self._pending_negative_to_evt = False
        self._heterogeneous_recharge_source = None
        self._heterogeneous_negative_to_evt = False
        self._heterogeneous_interpolation_method = "nearest"

    # dispatch -----------------------------------------------------------

    def required_runner(self) -> str:
        """Return the dispatch this model needs, 'subprocess' or 'api'.

        Only MODFLOW 6 has a choice to make, so the declaration lives here
        rather than in the shared helper: the caller asks the model instead of
        reading how it was built. Exposed-band (marnage) runoff coupling forces
        the in-process runner whatever the configuration says, because that
        coupling sets the LAK RUNOFF per timestep through the BMI API.
        """
        if self._exposed_band_runoff_specs:
            return "api"
        runner = getattr(self.modflow_config.runtime, "mf6_runner", "subprocess")
        return "api" if runner == "api" else "subprocess"

    # build helpers ------------------------------------------------------

    def _apply_preprocess_options(self, options: ModflowPreprocessOptions | None = None) -> None:
        apply_preprocess_options(self, options)

    def _xt3d_is_enabled(self, solver_mesh=None) -> bool:
        return xt3d_is_enabled(self, solver_mesh)

    def _xt3d_activation_mode(self, solver_mesh=None) -> str:
        return xt3d_mode(self, solver_mesh)

    def _resolve_xt3d_npf_options(self, solver_mesh=None) -> list[str] | None:
        return resolve_xt3d_options(self, solver_mesh)

    def resolved_solver_options(self) -> dict[str, object]:
        """Return what this model decided once built, for ``provenance.json``."""
        return {
            "ims_complexity": resolve_ims_complexity(self),
            "xt3d": self._xt3d_is_enabled(),
            "xt3d_source": self._xt3d_activation_mode(),
        }

    def _validate_pre_processing_inputs(self) -> None:
        validate_pre_processing_inputs(self)

    def pre_processing(
        self,
        model: Model,
        options: ModflowPreprocessOptions | None = None,
        *,
        slot: RunSlot | None = None,
    ):
        """Build the MODFLOW 6 simulation in memory, before it is written and run.

        Binds the model, applies the options, checks the inputs, then assembles
        the discretization and the flopy packages.

        Parameters
        ----------
        model
            The frozen ``Model``: its geometry (the cell mesh the grid is extruded
            from and the domain), properties, boundaries, sinks and sources, start
            state, time and options. It is kept as ``self.inputs`` and never changed.
        options
            Pre-processing options. None keeps the ones the solver holds.
        slot
            Where the run solves. The build reads its shared forcing folder, the
            folder a calibration trial keeps its recharge binaries in. None keeps
            every file beside the model.
        """
        run_pre_processing(self, model, options, slot=slot)

    # run --------------------------------------------------------------

    def processing(
        self,
        options: ModflowRunOptions | None = None,
        *,
        api_callback: Callable[[Mf6ApiContext], None] | None = None,
        api_lib_path: str | os.PathLike[str] | None = None,
    ):
        """Write and run the simulation, then return the success flag.

        When ``options.runner == "api"`` the solve is driven through libmf6
        instead of the mf6 executable. ``api_callback`` is an optional per-step
        developer hook and ``api_lib_path`` an optional explicit shared-library
        path; both are forwarded to the API runner and ignored in subprocess
        mode. They are passed in code only, never via TOML.
        """
        if api_callback is not None:
            self._mf6_api_callback = api_callback
        if api_lib_path is not None:
            self._mf6_api_lib_path = api_lib_path
        return run_processing(self, options)
