"""MODFLOW 6 GWT transport solver class."""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import flopy
import numpy as np
from pydantic import BaseModel

from hydromodpy.core.exceptions import SolverDivergedError, SolverInputError
from hydromodpy.model.model import Model
from hydromodpy.model.transport.transport_config import ConcentrationTransportParametersConfig
from hydromodpy.results.field_registry import FACE_FLOW
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow6.builders.solver_options import optional_ims_kwargs
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow6.support.computational_top import disv_grid_kwargs
from hydromodpy.solver.modflow6.support.names import mf6_safe_name
from hydromodpy.solver.modflow6.support.windows_paths import check_mf6_workspace_paths
from hydromodpy.solver.modflow_common.progress import (
    run_simulation_with_progress,
    write_listing_status,
)
from hydromodpy.solver.modflow_common.runtime_arrays import build_concentration_runtime_overrides

# The suffix of the transport model name a MODFLOW 6 GWT run writes, constant
# for this adapter: one concentration transport per run, so the index of the
# old plan-known suffix stays 1 (V4).
_MT_S1 = "_mt_s1"


class Modflow6Transport:
    """The MODFLOW 6 GWT transport solver of the ``flow/modflow6`` run.

    The solver is constructed from the ``Model`` its flow hands it and from the
    validated table of the transport, ``[transport.modflow6]``, read by
    ``options_of(name)``. Recharge (RCHA) is the only solute-injecting boundary:
    its concentration is carried as an auxiliary variable and wired into SSM.
    CHD and WEL inflows enter at concentration 0. Adding a solute source on
    those boundaries would edit the flow-side package construction; it is a
    deliberate future enhancement, not an oversight.
    """

    def __init__(
        self,
        model: Model,
        model_modflow: Modflow6,
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default_modflow6",
        suffix_name: str = _MT_S1,
        options: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ):
        """The MODFLOW 6 GWT transport solver of the flow run ``model`` extends.

        The solver is constructed from the ``Model`` of its flow, the one
        ``upstream[0].model`` of :class:`hydromodpy.solver.modflow6.adapter.Modflow6FlowAdapter`
        hands it, and from the validated table of the transport
        (``options``, the ``model_dump()`` of the ``[transport.modflow6]``
        block, validated by
        :class:`~hydromodpy.model.transport.transport_config.ConcentrationTransportParametersConfig`).
        """
        self.model = model
        self.domain = model.geometry.domain
        self.model_modflow = model_modflow
        self.model_folder = model_folder
        self.model_name = model_name
        self.suffix_name = suffix_name
        self.model_name_mt = model_name + suffix_name
        self.model_name_mt_mf6 = mf6_safe_name(self.model_name_mt)
        self.full_path = os.path.join(model_folder, model_name)

        conc_params = dict(options or {})
        conc_params.update(kwargs)
        conc_params.update(build_concentration_runtime_overrides(conc_params, model_modflow))

        self.sconc_init = conc_params.get("sconc_init", 0.0)
        self.sconc_input = conc_params.get("sconc_input", 0.0)
        self.disp_long = float(conc_params.get("disp_long", 0.0))
        self.disp_transh = float(conc_params.get("disp_transh", 0.0))
        self.disp_transv = float(conc_params.get("disp_transv", 0.0))
        self.diffu_coeff = float(conc_params.get("diffu_coeff", 0.0))
        self.react_order = conc_params.get("react_order", None)
        self.rate_decay = conc_params.get("rate_decay", 0.0)
        self.porosity = conc_params.get("porosity", None)
        self.scheme = conc_params.get("scheme", "upstream")

    def _resolve_mst_porosity(self):
        """Return effective porosity for MST: configured value, else specific yield.

        MST needs total porosity n, not specific yield Sy (the gravity-drainable
        fraction, smaller than n). Pore velocity is v = q / n, so falling back to
        Sy makes solute appear to move faster than reality; the fallback warns.
        """
        if self.porosity is not None:
            return float(self.porosity)
        warnings.warn(
            "No transport porosity set; falling back to the flow specific yield, which "
            "underestimates pore volume. Set the porosity of the transport in the "
            "[transport] table of the resolved configuration.",
            UserWarning,
            stacklevel=2,
        )
        nlay = int(self.model_modflow.nlay)
        ncpl = int(self.model_modflow.ncpl)
        sy = np.asarray(self.model_modflow.sy, dtype=float)
        if sy.size == 1:
            return np.full((nlay, ncpl), float(sy.reshape(-1)[0]), dtype=float)
        return sy.reshape(nlay, ncpl)

    def _warn_if_decay_annihilates_solute(self, decay_rate: float) -> None:
        """Warn when first-order decay wipes out the solute over the run.

        The MF6 GWT clock is SECONDS, so ``rate_decay`` is 1/s. A per-day value
        (~86400x too large) collapses the field within one output step. Flag the
        case where the simulation spans many decay half-lives. ``decay_rate`` is
        the fastest (max) per-cell rate for a conservative check.
        """
        perlen = getattr(self.model_modflow, "perlen", None)
        if perlen is None:
            return
        total_seconds = float(np.sum(np.asarray(perlen, dtype=float)))
        if total_seconds <= 0.0:
            return
        n_halflives = total_seconds * float(decay_rate) / float(np.log(2.0))
        if n_halflives > 30.0:
            warnings.warn(
                f"First-order decay removes the solute over the run "
                f"({n_halflives:.0f} half-lives). rate_decay is read in 1/s because "
                "the MF6 GWT clock is SECONDS; a per-day value is ~86400x too large. "
                "Set rate_decay in 1/s.",
                UserWarning,
                stacklevel=2,
            )

    def _build_crch(self) -> dict[int, np.ndarray]:
        nper = int(self.model_modflow.nper)
        ncpl = int(self.model_modflow.ncpl)
        if isinstance(self.sconc_input, dict):
            out = {}
            for k in range(nper):
                arr = self.sconc_input.get(k)
                if arr is None:
                    arr = np.zeros(ncpl, dtype=float)
                out[k] = np.asarray(arr, dtype=float).reshape(-1)
            return out
        val = float(self.sconc_input)
        return {k: np.full(ncpl, val, dtype=float) for k in range(nper)}

    def pre_processing(self):
        sim = self.model_modflow.sim
        self.gwf = self.model_modflow.gwf
        runtime = self.model_modflow.modflow_config.runtime
        # GWT advection produces a non-symmetric system. CG (the flow preset
        # under SIMPLE) diverges on it, so force BICGSTAB for transport
        # regardless of the flow linear_acceleration preset.
        ims_kwargs = optional_ims_kwargs(runtime)
        ims_kwargs["linear_acceleration"] = "BICGSTAB"
        self.ims = flopy.mf6.ModflowIms(
            sim,
            print_option="SUMMARY" if runtime.mf_verbose else "NONE",
            # Transport is linear: use the configured complexity, no Newton promotion.
            complexity=runtime.mf6_ims_complexity,
            outer_dvclose=float(runtime.mf6_outer_dvclose),
            inner_dvclose=float(runtime.mf6_inner_dvclose),
            outer_maximum=int(runtime.mf6_outer_maximum),
            inner_maximum=int(runtime.mf6_inner_maximum),
            filename=f"{self.model_name_mt_mf6}.ims",
            pname="IMS_GWT",
            **ims_kwargs,
        )
        self.gwt = flopy.mf6.ModflowGwt(sim, modelname=self.model_name_mt_mf6, save_flows=True)
        sim.register_ims_package(self.ims, [self.gwt.name])
        if hasattr(self.model_modflow, "ims") and self.model_modflow.ims is not None:
            sim.name_file.solutiongroup.set_data(
                [
                    ("ims6", self.model_modflow.ims.filename, self.gwf.name),
                    ("ims6", self.ims.filename, self.gwt.name),
                ],
                key=0,
            )

        # GWT must share the GWF grid for a valid GWF6-GWT6 exchange.
        self.gwtdis = flopy.mf6.ModflowGwtdisv(self.gwt, **disv_grid_kwargs(self.model_modflow))
        self.gwtic = flopy.mf6.ModflowGwtic(self.gwt, strt=self.sconc_init)
        self.adv = flopy.mf6.ModflowGwtadv(self.gwt, scheme=self.scheme)
        # DSP only matters when dispersion or molecular diffusion is non-zero.
        # Skip it for pure advection so MF6 does not assemble an all-zero
        # dispersion tensor.
        self.dsp = None
        if self.disp_long > 0.0 or self.diffu_coeff > 0.0:
            self.dsp = flopy.mf6.ModflowGwtdsp(
                self.gwt,
                alh=self.disp_long,
                ath1=self.disp_long * self.disp_transh,
                atv=self.disp_long * self.disp_transv,
                diffc=self.diffu_coeff,
            )

        # MF6 selects the decay model with distinct flags; pick exactly one.
        mst_porosity = self._resolve_mst_porosity()
        if self.react_order == 0:
            self.mst = flopy.mf6.ModflowGwtmst(
                self.gwt, porosity=mst_porosity, zero_order_decay=True, decay=self.rate_decay
            )
        elif self.react_order == 1:
            self.mst = flopy.mf6.ModflowGwtmst(
                self.gwt, porosity=mst_porosity, first_order_decay=True, decay=self.rate_decay
            )
        else:
            self.mst = flopy.mf6.ModflowGwtmst(self.gwt, porosity=mst_porosity)
        decay_arr = np.asarray(self.rate_decay, dtype=float)
        if self.react_order == 1 and decay_arr.size and float(np.nanmax(decay_arr)) > 0.0:
            self._warn_if_decay_annihilates_solute(float(np.nanmax(decay_arr)))

        if not hasattr(self.model_modflow, "rch") or self.model_modflow.rch is None:
            raise RuntimeError("Modflow6Transport requires an existing GWF recharge package.")
        self.model_modflow.rch.aux.set_data(
            {k: [np.asarray(v, dtype=float)] for k, v in self._build_crch().items()}
        )
        self.ssm = flopy.mf6.ModflowGwtssm(self.gwt, sources=[("RCHA", "AUX", "CONCENTRATION")])

        self.gwfgwt = flopy.mf6.ModflowGwfgwt(
            sim,
            exgtype="GWF6-GWT6",
            exgmnamea=self.gwf.name,
            exgmnameb=self.gwt.name,
        )
        self.oc = flopy.mf6.ModflowGwtoc(
            self.gwt,
            concentration_filerecord=f"{self.model_name_mt}.ucn",
            budget_filerecord=f"{self.model_name_mt}.cbc",
            saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
        )

    def processing(self, write_model: bool = True, run_model: bool = False, verbose: bool = True):
        del verbose  # the write listing always goes to the debug log
        if write_model:
            with write_listing_status("Writing transport input files"):
                self.model_modflow.sim.write_simulation(silent=False)
        success = False
        if run_model:
            check_mf6_workspace_paths(self.model_modflow.sim)
            success, _ = run_simulation_with_progress(
                self.model_modflow.sim,
                int(self.model_modflow.nper),
                description="Solving transport stress periods",
            )
        return success


class Modflow6GwtTransportAdapter:
    """Port adapter of ``transport/modflow6``, beside its engine class.

    GWT extends the simulation of the flow run it follows, in the folder that
    flow wrote in, under the name of its model plus the suffix ``_mt_s1``. The
    parameters of the deck are the validated ``[transport.modflow6]`` table the
    runner holds, and reach the engine as one mapping.
    """

    name: ClassVar[str] = "modflow6"
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = ("concentration/*", "mass_balance")
    reads: ClassVar[tuple[str, ...]] = (FACE_FLOW,)
    supports: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type[BaseModel] | None] = ConcentrationTransportParametersConfig
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow6"),)

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """Nothing to refuse here: every table is validated while the file is read."""
        return None

    def build(
        self,
        model: Any,
        options: BaseModel | None = None,
        slot: RunSlot | None = None,
        upstream: tuple[SolverRun, ...] = (),
    ) -> SolverRun:
        """Build the GWT model of the one flow run ``upstream`` names, in memory."""
        (followed,) = upstream
        if followed.solver_model is None:
            raise SolverInputError(
                f"Transport '{self.name}' follows a flow run whose model is missing. "
                "GWT extends the MODFLOW 6 objects of the flow, and none was built."
            )
        flow_model = followed.solver_model
        model_folder = (
            str(followed.slot.folder)
            if followed.slot is not None
            else (
                str(followed.output_dir.parent)
                if followed.output_dir is not None
                else "HydroModPy_outputs"
            )
        )
        solver_model = Modflow6Transport(
            followed.model,
            flow_model,
            model_folder=model_folder,
            model_name=str(flow_model.model_name),
            suffix_name=_MT_S1,
            options=None if options is None else options.model_dump(),
        )
        solver_model.pre_processing()
        return SolverRun(slot=slot, model=model, options=options, solver_model=solver_model)

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Write the GWT input files unless they are written, solve, and return the run."""
        solver_model = solver_run.solver_model
        success = solver_model.processing(
            write_model=not solver_run.written, run_model=True, verbose=True
        )
        if not success:
            raise SolverDivergedError(
                f"Transport solver '{self.name}' failed for run '{solver_run.slot.name}', "
                f"see {getattr(solver_model, 'full_path', '<unknown>')} for diagnostics."
            )
        return replace(
            solver_run,
            output_dir=Path(solver_model.full_path),
            written=True,
            solved=True,
        )

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the concentration and the solute balance through the registered extractor."""
        extractors.create(self.process_type, self.name).extract(solver_run, store, retention)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch directory written by this run, if any."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)


__all__ = ["Modflow6GwtTransportAdapter", "Modflow6Transport"]
