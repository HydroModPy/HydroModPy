"""MODFLOW 6 GWT transport solver class."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace

import flopy
import numpy as np

from hydromodpy.solver.modflow6.postprocess import run_transport_post_processing
from hydromodpy.solver.modflow_common import (
    ModflowPostprocessOptions,
    build_concentration_runtime_overrides,
)


def _mf6_safe_name(name: str, max_len: int = 16) -> str:
    import hashlib

    text = str(name)
    if len(text) <= max_len:
        return text
    if max_len <= 6:
        return text[:max_len]
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    prefix_len = max_len - 7
    return f"{text[:prefix_len]}_{digest}"


class Modflow6Transport:
    """Transport solver based on MODFLOW 6 GWT and `transport.modflow6gwt.parameters`."""

    def __init__(
        self,
        domain: object,
        transport: object,
        model_modflow: object,
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
        self.model_name_mt_mf6 = _mf6_safe_name(self.model_name_mt)
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
        self.plot_conc = bool(conc_params.get("plot_conc", True))

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
        self.ims = flopy.mf6.ModflowIms(
            sim,
            print_option="SUMMARY",
            complexity="COMPLEX",
            filename=f"{self.model_name_mt_mf6}.ims",
            pname="IMS_GWT",
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
        self.gwtdis = flopy.mf6.ModflowGwtdisv(
            self.gwt,
            nlay=self.model_modflow.nlay,
            **disv_kwargs,
        )
        self.gwtic = flopy.mf6.ModflowGwtic(self.gwt, strt=self.sconc_init)
        self.adv = flopy.mf6.ModflowGwtadv(self.gwt, scheme="upstream")
        self.dsp = flopy.mf6.ModflowGwtdsp(
            self.gwt,
            alh=self.disp_long,
            ath1=self.disp_long * self.disp_transh,
            atv=self.disp_long * self.disp_transv,
            diffc=self.diffu_coeff,
        )

        decay = self.rate_decay if self.react_order in {0, 1} else None
        self.mst = flopy.mf6.ModflowGwtmst(
            self.gwt,
            porosity=self.model_modflow.sy,
            first_order_decay=bool(self.react_order == 1),
            decay=decay,
        )

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
