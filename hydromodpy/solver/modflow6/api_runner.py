"""Developer-facing MODFLOW 6 API runner driven by libmf6.so.

This is a parallel, opt-in entry point to the normal subprocess path in
``run.py``. It drives an *already-written* simulation workspace through the
MODFLOW 6 shared library (``libmf6.so``) using the optional ``modflowapi``
package, invoking a developer callback once per timestep.

The callback receives a typed :class:`Mf6ApiContext`, never raw
``modflowapi`` objects, so the public surface does not leak the optional
dependency's types. The context hides the AdvancedPackage / pointer
mechanics behind read/write accessors for lake stage and GWF heads, plus a
raw escape hatch (``get_value`` / ``set_value`` / ``get_value_ptr``) for any
other forcing or release value.

``modflowapi`` and ``xmipy`` are OPTIONAL: they are imported lazily inside
:func:`run_mf6_api` so importing this module stays cheap and dependency-free.
Install them with ``pip install modflowapi xmipy`` (or the ``mf6api`` extra).

Notes
-----
The simulation must already be written (``mfsim.nam`` present in ``sim_ws``).
For an HydroModPy model, run ``pre_processing`` then
``processing(ModflowRunOptions(run_model=False))`` (or
``model.sim.write_simulation(...)``) before calling :func:`run_mf6_api`,
then pass ``model.full_path`` as ``sim_ws``.

The MODFLOW 6 LAK package exposes the *input* starting stage as the advanced
variable ``"stage"`` and the *solved* post-solve stage as ``"xnewpak"``.
:meth:`Mf6ApiContext.read_lake_stage` reads the solved stage by default;
:meth:`Mf6ApiContext.write_lake_stage` overrides the input ``"stage"`` value
so the change forces the solution. Both validate the variable name against
the package's ``advanced_vars`` at runtime and raise a clear error rather
than failing deep in xmipy. Run with ``_develop=True`` to dump a
``var_list.txt`` of every accessible address as a discovery aid.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import SolverError
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.binaries import ensure_solver_library

logger = get_logger(__name__)

__all__ = ["Mf6ApiContext", "Mf6ApiStep", "run_mf6_api"]


class Mf6ApiStep(IntEnum):
    """Simulation phase at which the developer callback fires.

    Mirrors the ``modflowapi.Callbacks`` enum values for the phases this
    runner exposes, so developers never import ``modflowapi`` directly.
    """

    initialize = 0
    timestep_start = 3
    timestep_end = 4
    finalize = 7


@dataclass
class Mf6ApiContext:
    """Typed view over one MODFLOW 6 solution group at a callback phase.

    The accessors operate on ``_sim`` (a ``modflowapi`` ApiSimulation) and
    hide the AdvancedPackage / pointer mechanics. ``_sim`` is private so the
    public surface does not leak the optional dependency's types.
    """

    step: Mf6ApiStep
    kper: int
    kstp: int
    totim: float
    _sim: Any

    # model / package resolution -------------------------------------------

    def model(self, name: str | None = None) -> Any:
        """Return the modflowapi ApiModel proxy by name (or the first model)."""
        return self._sim.get_model(name)

    def _resolve_model(self, model: Any | None) -> Any:
        if model is None:
            return self._sim.get_model()
        if isinstance(model, str):
            return self._sim.get_model(model)
        return model

    def _lake_package(self, model: Any | None, pkg: str | None) -> Any:
        api_model = self._resolve_model(model)
        if pkg is not None:
            return api_model.get_package(pkg)
        for name in api_model.package_names:
            package = api_model.get_package(name)
            if getattr(package, "pkg_type", "").lower() == "lak":
                return package
        raise SolverError(
            "No LAK package found in the model. Available packages: "
            f"{list(api_model.package_names)}."
        )

    @staticmethod
    def _resolve_advanced_var(package: Any, name: str) -> str:
        """Return the advanced var name matching ``name`` case-insensitively."""
        available = list(getattr(package, "advanced_vars", []))
        lowered = name.lower()
        if lowered in available:
            return lowered
        raise SolverError(
            f"Advanced variable {name!r} is not accessible for package "
            f"{getattr(package, 'pkg_name', '?')!r}. "
            f"Available advanced variables: {sorted(available)}."
        )

    # lake stage -----------------------------------------------------------

    def read_lake_stage(
        self,
        model: Any | None = None,
        pkg: str | None = None,
        *,
        var: str = "xnewpak",
    ) -> np.ndarray:
        """Read the per-lake stage as a 1-D array.

        Defaults to the *solved* stage (``"xnewpak"``), which matches the
        saved LAK stage output. Pass ``var="stage"`` to read the input
        starting stage instead.
        """
        package = self._lake_package(model, pkg)
        resolved = self._resolve_advanced_var(package, var)
        return np.asarray(package.get_advanced_var(resolved)).ravel()

    def write_lake_stage(
        self,
        values: Sequence[float] | np.ndarray,
        model: Any | None = None,
        pkg: str | None = None,
        *,
        var: str = "stage",
    ) -> None:
        """Override the lake stage forcing value (default the input ``stage``).

        Writing the input ``"stage"`` value forces the solution for the
        current and following timesteps. ``values`` is coerced to a
        C-contiguous ``float64`` array.
        """
        package = self._lake_package(model, pkg)
        resolved = self._resolve_advanced_var(package, var)
        array = np.ascontiguousarray(np.asarray(values, dtype=np.float64)).ravel()
        package.set_advanced_var(resolved, array)

    # heads ----------------------------------------------------------------

    def read_heads(self, model: Any | None = None) -> np.ndarray:
        """Return a read-only copy of the GWF heads reshaped to the grid."""
        api_model = self._resolve_model(model)
        return np.asarray(api_model.X)

    def write_heads(self, values: Sequence[float] | np.ndarray, model: Any | None = None) -> None:
        """Overwrite the live GWF head vector via the solver pointer.

        ``ApiModel.X`` is read-only, so heads are written through the raw
        ``X`` pointer (reduced-node ordering). ``values`` must match the
        pointer length; it is coerced to a C-contiguous ``float64`` array.
        """
        api_model = self._resolve_model(model)
        mf6 = self._sim.mf6
        addr = mf6.get_var_address("X", api_model.name)
        ptr = mf6.get_value_ptr(addr)
        array = np.ascontiguousarray(np.asarray(values, dtype=np.float64)).ravel()
        if array.size != ptr.size:
            raise SolverError(
                f"write_heads expected {ptr.size} values for the live head "
                f"pointer but got {array.size}."
            )
        ptr[:] = array

    # raw escape hatch -----------------------------------------------------

    def get_value(self, addr: str) -> np.ndarray:
        """Return a copy of the raw solver variable at ``addr`` (XmiWrapper)."""
        return np.asarray(self._sim.mf6.get_value(addr))

    def set_value(self, addr: str, values: Sequence[float] | np.ndarray) -> None:
        """Set the raw solver variable at ``addr`` (C-contiguous float64)."""
        array = np.ascontiguousarray(np.asarray(values, dtype=np.float64)).ravel()
        self._sim.mf6.set_value(addr, array)

    def get_value_ptr(self, addr: str) -> np.ndarray:
        """Return the live pointer to the raw solver variable at ``addr``."""
        return self._sim.mf6.get_value_ptr(addr)


def _read_tdis_scalars(sim: Any) -> tuple[int, int, float]:
    """Read kper / kstp / totim defensively across all callback phases.

    The modflowapi convenience properties raise before the first timestep
    (TOTIM is unset at initialize) and ``sim.totim`` is unreachable due to an
    upstream typo, so we read the raw ``TDIS`` addresses directly and fall
    back to safe zeros.
    """

    def _scalar(name: str, default: float) -> float:
        try:
            addr = sim.mf6.get_var_address(name, "TDIS")
            return float(sim.mf6.get_value(addr).ravel()[0])
        except Exception:
            return default

    kper = int(_scalar("KPER", 1.0)) - 1
    kstp = int(_scalar("KSTP", 1.0)) - 1
    totim = _scalar("TOTIM", 0.0)
    return max(kper, 0), max(kstp, 0), totim


def run_mf6_api(
    sim_ws: str | os.PathLike[str],
    callback: Callable[[Mf6ApiContext], None],
    *,
    lib_path: str | os.PathLike[str] | None = None,
    verbose: bool = False,
) -> bool:
    """Drive a written MODFLOW 6 workspace through libmf6 with a step callback.

    Parameters
    ----------
    sim_ws:
        Workspace containing ``mfsim.nam`` (already written). For an
        HydroModPy model pass ``model.full_path``.
    callback:
        Developer hook invoked once per timestep (at
        :attr:`Mf6ApiStep.timestep_end`) plus at initialize and finalize.
        It receives a typed :class:`Mf6ApiContext`.
    lib_path:
        Explicit path to the MODFLOW 6 shared library. When ``None`` the
        managed cache copy of ``libmf6`` is resolved.
    verbose:
        Forward verbose output from the modflowapi runner.

    Returns
    -------
    bool
        Convergence / success flag.

    Raises
    ------
    ImportError
        When the optional ``modflowapi`` package is not installed.
    FileNotFoundError
        When ``sim_ws/mfsim.nam`` or the shared library is missing.
    SolverError
        When the developer callback raises (re-raised with step context).
    """
    try:
        import modflowapi
    except ImportError as exc:
        raise ImportError(
            "run_mf6_api requires the optional 'modflowapi' package (and 'xmipy'). "
            "Install with: pip install modflowapi xmipy"
        ) from exc

    workspace = Path(sim_ws).expanduser()
    nam = workspace / "mfsim.nam"
    if not nam.is_file():
        raise FileNotFoundError(
            f"No mfsim.nam in {workspace}. The simulation must be written first "
            f"(e.g. model.sim.write_simulation(...) or "
            f"processing(ModflowRunOptions(run_model=False)))."
        )

    if lib_path is not None:
        resolved_lib = Path(lib_path).expanduser().resolve()
        if not resolved_lib.is_file():
            raise FileNotFoundError(f"MODFLOW 6 shared library not found: {resolved_lib}")
    else:
        resolved_lib = ensure_solver_library("libmf6").resolve()

    callbacks = modflowapi.Callbacks
    phase_by_callback = {
        callbacks.initialize: Mf6ApiStep.initialize,
        callbacks.timestep_start: Mf6ApiStep.timestep_start,
        callbacks.timestep_end: Mf6ApiStep.timestep_end,
        callbacks.finalize: Mf6ApiStep.finalize,
    }

    def _native_callback(sim: Any, mf_step: Any) -> None:
        phase = phase_by_callback.get(mf_step)
        if phase is None:
            return
        kper, kstp, totim = _read_tdis_scalars(sim)
        ctx = Mf6ApiContext(
            step=phase,
            kper=kper,
            kstp=kstp,
            totim=totim,
            _sim=sim,
        )
        try:
            callback(ctx)
        except Exception as exc:
            raise SolverError(
                f"MF6 API callback failed at {phase.name} "
                f"(kper={ctx.kper}, kstp={ctx.kstp}, totim={ctx.totim}): {exc}"
            ) from exc

    if verbose:
        logger.info("Running MF6 API on %s with %s", workspace, resolved_lib.name)

    success = modflowapi.run_simulation(
        str(resolved_lib), str(workspace), _native_callback, verbose=verbose
    )
    # modflowapi.run_simulation returns None on normal termination; treat a
    # completed run without an exception as a success.
    return True if success is None else bool(success)
