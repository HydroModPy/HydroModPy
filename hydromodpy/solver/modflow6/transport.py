"""MODFLOW 6 GWT transport solver class."""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping
from dataclasses import replace

import flopy
import numpy as np

from hydromodpy.solver.base.protocols import DomainLike, FlowModelLike, TransportLike
from hydromodpy.solver.modflow6.build import mf6_safe_name, optional_ims_kwargs
from hydromodpy.solver.modflow6.postprocess import run_transport_post_processing
from hydromodpy.solver.modflow_common import (
    ModflowPostprocessOptions,
    build_concentration_runtime_overrides,
)


class Modflow6Transport:
    """Transport solver based on MODFLOW 6 GWT and `transport.modflow6gwt.parameters`.

    Recharge (RCHA) is the only solute-injecting boundary: its concentration is
    carried as an auxiliary variable and wired into SSM. CHD and WEL inflows enter
    at concentration 0. Adding a solute source on those boundaries would edit the
    flow-side package construction; it is a deliberate future enhancement, not an
    oversight.
    """

    def __init__(
        self,
        domain: DomainLike,
        transport: TransportLike,
        model_modflow: FlowModelLike,
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default_modflow6",
        suffix_name: str = "_gwt",
        bin_path: str | None = None,
        **kwargs,
    ):
        self.domain = domain
        self.transport = transport
        self.model_modflow = model_modflow
        self.model_folder = model_folder
        self.model_name = model_name
        self.suffix_name = suffix_name
        self.model_name_mt = model_name + suffix_name
        self.model_name_mt_mf6 = mf6_safe_name(self.model_name_mt)
        self.full_path = os.path.join(model_folder, model_name)
        self.exe = getattr(model_modflow, "exe", "mf6")

        conc_params = {}
        comp = transport.modflow6gwt
        if isinstance(getattr(comp, "parameters", None), Mapping):
            conc_params = dict(comp.parameters)
        conc_params.update(kwargs)
        conc_params.update(build_concentration_runtime_overrides(conc_params, model_modflow))

        self.spc_name = conc_params.get("spc_name", "NO3")
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
        self.plot_conc = bool(conc_params.get("plot_conc", True))

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
            "underestimates pore volume. Set transport.modflow6gwt.parameters.porosity.",
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

    def _build_crch_aux(self) -> dict[int, list[np.ndarray]]:
        crch = self._build_crch()
        return {k: [np.asarray(v, dtype=float)] for k, v in crch.items()}

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

        disv_kwargs = self.model_modflow.solver_mesh.to_disv_kwargs()
        # GWT must share the GWF active domain for a valid GWF6-GWT6 exchange.
        # DISV vertices are absolute model coordinates, so the package origin
        # must be 0 to match the GWF and PRT grids (no double offset).
        self.gwtdis = flopy.mf6.ModflowGwtdisv(
            self.gwt,
            nlay=self.model_modflow.nlay,
            **disv_kwargs,
            idomain=self.model_modflow.solver_mesh.idomain(),
            xorigin=0.0,
            yorigin=0.0,
            length_units="METERS",
        )
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
        self.model_modflow.rch.aux.set_data(self._build_crch_aux())
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
        if write_model:
            self.model_modflow.sim.write_simulation(silent=not verbose)
        success = False
        if run_model:
            success, _ = self.model_modflow.sim.run_simulation(silent=not verbose)
        return success

    def _resolve_postprocess_options(
        self,
        *,
        export_all_tif: bool,
        options: ModflowPostprocessOptions | None,
    ) -> ModflowPostprocessOptions:
        """Resolve transport post-processing options from explicit or inherited flow settings."""
        if options is not None and not isinstance(options, ModflowPostprocessOptions):
            raise TypeError("transport post_processing options must be ModflowPostprocessOptions")

        resolved = options
        if resolved is None:
            inherited = getattr(self.model_modflow, "last_postprocess_options", None)
            if isinstance(inherited, ModflowPostprocessOptions):
                resolved = inherited
        if resolved is None:
            return ModflowPostprocessOptions(export_all_tif=bool(export_all_tif))
        if bool(getattr(resolved, "export_all_tif", False)) == bool(export_all_tif):
            return resolved
        return replace(resolved, export_all_tif=bool(export_all_tif))

    def post_processing(
        self,
        model_mt3dms: object,
        concentration_seepage: bool = True,
        mass_seepage: bool = True,
        mass_accumulated: bool = False,
        export_all_tif: bool = False,
        options: ModflowPostprocessOptions | None = None,
    ) -> None:
        run_transport_post_processing(
            self,
            model_mt3dms,
            concentration_seepage=concentration_seepage,
            mass_seepage=mass_seepage,
            mass_accumulated=mass_accumulated,
            export_all_tif=export_all_tif,
            options=options,
        )


__all__ = ["Modflow6Transport"]
