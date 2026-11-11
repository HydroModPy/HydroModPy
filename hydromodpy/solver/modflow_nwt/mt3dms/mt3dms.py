"""The MT3DMS transport model on a MODFLOW-NWT flow, and its transport adapter.

Created on Thu Apr  3 13:06:53 2025 by rabherve.
"""

# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

# %% LIBRAIRIES

# Python
import os
import shutil
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import flopy
import flopy.utils.binaryfile as bf
import numpy as np
import rasterio

# HydroModPy
from pydantic import BaseModel

from hydromodpy.core.exceptions import SolverDivergedError, SolverInputError
from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.core.logging import get_logger
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.transport.transport_config import ConcentrationTransportParametersConfig
from hydromodpy.results.field_registry import FACE_FLOW
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.flow_run import nwt_safe_name
from hydromodpy.solver.modflow_common.runtime_arrays import (
    build_concentration_runtime_overrides,
)
from hydromodpy.solver.modflow_nwt.modpath.resolvers import get_raster
from hydromodpy.solver.modflow_nwt.mt3dms import masstransfer
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt

MT3DMS_NORMAL_MESSAGES = ["normal termination", "program completed"]

# %% CLASS


class Mt3dms:
    """
    Class Modpath.

    To build, run particle traccking from modflow simulation.
    """

    def __init__(
        self,
        domain: Domain,
        params: Mapping[str, object] | None = None,
        model_modflow: ModflowNwt | None = None,
        # Worflow settings
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default_modpath",
        suffix_name: str = "_mt",
        bin_path: str | os.PathLike[str] | None = None,
        # Specific settings
        spc_name: str | None = None,
        sconc_init: float | None = None,
        sconc_input=None,
        disp_long: float | None = None,
        disp_transh: float | None = None,
        disp_transv: float | None = None,
        diffu_coeff: float | None = None,
        react_order: int | None = None,  # for MT3DM: 0, 1, 100
        rate_decay: float | None = None,
        plot_conc: bool | None = None,
    ):
        """
        Initialize method.

        Parameters
        ----------
        domain : object
            Domain object build by HydroModPy.
        params : Mapping, optional
            The validated concentration parameters of the run, flattened to
            scalar values (``options.model_dump()["parameters"]`` of the
            ``[transport.mt3dms]`` table). Empty means every default of the
            engine, and the explicit parameters below override it.
        """

        # %% Initialization

        if model_modflow is None:
            raise ValueError("model_modflow must be provided to initialize Mt3dms")

        self.domain = domain
        self.params = dict(params or {})
        self.model_modflow = model_modflow
        self.raster = get_raster(model_modflow)

        self.model_folder = model_folder
        self.model_name = model_name
        self.full_path = os.path.join(model_folder, model_name)
        self.suffix_name = suffix_name
        self.model_name_mt = model_name + self.suffix_name

        if not os.path.isdir(self.full_path):
            raise FileNotFoundError(f"Directory not found: {self.full_path}")
        self.exe = str(ensure_solver_binary("mt3dusgs", bin_path))

        conc_params = dict(self.params)

        explicit_params = {
            "spc_name": spc_name,
            "sconc_init": sconc_init,
            "sconc_input": sconc_input,
            "disp_long": disp_long,
            "disp_transh": disp_transh,
            "disp_transv": disp_transv,
            "diffu_coeff": diffu_coeff,
            "react_order": react_order,
            "rate_decay": rate_decay,
            "plot_conc": plot_conc,
        }
        for key, value in explicit_params.items():
            if value is not None:
                conc_params[key] = value

        runtime_overrides = build_concentration_runtime_overrides(
            conc_params,
            model_modflow,
        )
        conc_params.update(runtime_overrides)

        self.spc_name = conc_params.get("spc_name", "NO3")
        self.sconc_init = conc_params.get("sconc_init", 0)
        self.sconc_input = conc_params.get("sconc_input", 0)

        self.disp_long = conc_params.get("disp_long", 0)
        self.disp_transh = conc_params.get("disp_transh", 0)
        self.disp_transv = conc_params.get("disp_transv", 0)
        self.diffu_coeff = conc_params.get("diffu_coeff", 0)

        self.react_order = conc_params.get("react_order", None)
        self.rate_decay = conc_params.get("rate_decay", 0)

        self.plot_conc = conc_params.get("plot_conc", True)

        self.mf = model_modflow.mf

        self.new_stepsize = 1

    # %% PRE-PROCESSING

    def pre_processing(self):
        """
        Pre-processing to build the trasnport model.

        Returns
        -------
        None.

        """

        self.mt = flopy.mt3d.Mt3dms(
            modflowmodel=self.mf,
            modelname=self.model_name_mt,
            version="mt3d-usgs",
            model_ws=self.full_path,
            exe_name=self.exe,
            ftlfilename="mt3d_link.ftl",
            namefile_ext="mtnam",
            verbose=False,
            ftlfree=False,
        )

        flopy.mt3d.Mt3dGcg(
            self.mt,
            mxiter=10,
            # cclose=1e-7,
            # iter1=1000
        )

        # %% Specific parametrization

        self.ssflag = [
            "True"
        ]  # This one is for the transport simulation (STEADY FOR THE FIRST PERIOD)
        for _i in range((self.mf.nper - 1) * self.new_stepsize):
            self.ssflag.append(" ")

        self.btn = flopy.mt3d.Mt3dBtn(
            self.mt,
            nlay=self.mf.nlay,
            nrow=self.mf.nrow,
            ncol=self.mf.ncol,
            delr=np.asarray(self.model_modflow.dis.delr.array, dtype=float),
            delc=np.asarray(self.model_modflow.dis.delc.array, dtype=float),
            nper=self.mf.nper,  # mf.nper*new_stepsize+1
            nprs=self.mf.nper,  # mf.nper*new_stepsize+1
            nstp=self.model_modflow.nstp,
            perlen=self.model_modflow.perlen,
            prsity=self.model_modflow.sy,
            sconc=self.sconc_init,
            laycon=1,
            ncomp=1,
            mcomp=1,
            tsmult=1,
            nprmas=0,
            thkmin=0.01,  # 0.0001/(delv/nlay))
            icbund=1,
            timprs=[self.mf.nper],
            ssflag=self.ssflag,
            species_names=self.spc_name,
            cinact=1e30,
            Legacy99Stor=True,
            NoWetDryPrint=True,
            MFStyleArr=True,
            obs=None,
            savucn=True,
            DRYCell=True,
            chkmas=True,
            unitnumber=None,
            tunit="D",
            lunit="M",
            munit="KG",
        )

        # %% Advection package

        flopy.mt3d.Mt3dAdv(
            self.mt,
            mixelm=-1,
            # percel=0.75
        )
        # Solution method (mixelm)
        # • Finite Difference Method (FDM)
        # • MOC : Method of Characteristics (MOC)
        # • MMOC : Modified Method of Characteristics (MMOC)
        # • HMOC : Hybrid Method of Characteristics (HMOC)
        # • TVD (MIXELM = -1 - try to use this one)

        # %% Dispersion package

        self.disp = flopy.mt3d.mtdsp.Mt3dDsp(
            self.mt,
            al=self.disp_long,  # unit L
            trpt=self.disp_transh,  # ratio of the horizontal transverse dispersivity to the longitudinal dispersivity, 10x moins
            trpv=self.disp_transv,  # ratio of the vertical transverse dispersivity to the longitudinal dispersivity, 100x moins
            dmcoef=self.diffu_coeff,  # L2T-1
            extension="dsp",
        )  # Not used for the moment

        # %% Reactivity package

        if self.react_order is None:
            ireact = 0
        if self.react_order == 1:
            ireact = 1
        if self.react_order == 0:
            ireact = 100
        self.rct = flopy.mt3d.mtrct.Mt3dRct(
            self.mt,
            isothm=0,  # no sorption is simulated
            ireact=ireact,  # 0: no-reaction, 1: first-order, 100: zero-order
            igetsc=0,  # 0 : the initial concentration for the sorbed or immobile phase is not read
            rhob=None,
            rc1=self.rate_decay,  # (unit, T-1)
        )

        # %% Concentration package

        self.ssm = flopy.mt3d.Mt3dSsm(
            self.mt,
            crch=self.sconc_input,
            mxss=None,  # mxss=mf.nrow*mf.ncol*(nper*new_stepsize+1)+10,
            stress_period_data=None,
        )

    # %% PROCESSING

    def processing(self, write_model: bool = True, run_model: bool = False, verbose: bool = True):
        """
        Run the trasnport model.

        Parameters
        ----------
        write_model : bool, optional
            Flag to write input files or not. The default is True.
        run_model : bool, optional
            Flag to run model or not. The default is False.

        Returns
        -------
        success_model : bool
            Flag to know if the simulation finished correctly.

        """
        # Create modflow files
        if write_model:
            self.mt.write_input()

        # Run modflow files
        success_model = True

        if run_model:
            if verbose is False:
                logger.info("Running MT3DMS transport simulation")
            success_model, tempo = self.mt.run_model(
                silent=not verbose,
                pause=False,
                # report=True,
                normal_msg=MT3DMS_NORMAL_MESSAGES,
            )  # True without msg

        shutil.copy(
            os.path.join(self.full_path, "MT3D001.UCN"),
            os.path.join(self.full_path, self.model_name_mt + ".UCN"),
        )

        return success_model

    # %% POST-PROCESSING

    def post_processing(
        self,
        model_mt3dms: object,
        geographic: object | None = None,
        concentration_seepage: bool = True,
        mass_seepage: bool = True,
        mass_accumulated: bool = False,
        export_all_tif: bool = False,
    ):
        """
        Create outputs files.

        An MT3DMS post-processing reads nothing on the flow model itself: the
        geographic context of its flow (the DEM raster, the routing grid, the
        masks and the reference raster) comes in as one argument and is read
        here instead. ``model_mt3dms`` is accepted for signature parity with
        the plain MT3DMS workflow and never read.

        Parameters
        ----------
        geographic : object
            The geographic context of the flow run this transport follows,
            read off ``Model.geometry`` (its DEM raster, routing grid and
            masks). It carries everything the outputs are built on.
        """
        # Create folders
        self.save_file = os.path.join(self.full_path, "_postprocess")
        create_folder(self.save_file)

        self.figure_file = os.path.join(self.full_path, "_postprocess", "_figures")
        create_folder(self.figure_file)

        self.temporary_file = os.path.join(self.full_path, "_postprocess", "_temporary")
        create_folder(self.temporary_file)

        self.tifs_file = os.path.join(self.full_path, "_postprocess", "_rasters")
        create_folder(self.tifs_file)

        self.save_fig = os.path.join(self.model_folder, "_figures")
        create_folder(self.save_fig)

        # %% Load what the post-processing derives, off the geographic

        self.inactive_mask = np.asarray(getattr(geographic, "inactive_mask", None), dtype=bool)
        self.outflow_drain = dict(getattr(geographic, "dict_outflow_drain", None) or {})
        self.nper = int(getattr(geographic, "nper", 0) or 0)

        # The reference raster and the routing paths of the flow run
        self.dem_watershed_path = getattr(geographic, "dem_watershed_path", None)
        routing_ctx = getattr(geographic, "routing_ctx", None)
        self.routing_fill_path = getattr(routing_ctx, "correc_path", None)
        self.routing_direc_path = getattr(routing_ctx, "direc_path", None)

        # %% Load essential data

        # Modflow specific files (written in the processing phase)
        self.path_file = os.path.join(self.full_path, self.model_name_mt + ".UCN")

        self.ucnobj = bf.UcnFile(self.path_file)
        ucn_all_data = None
        if hasattr(self.ucnobj, "get_times"):
            ucn_times = list(self.ucnobj.get_times())
        else:
            ucn_all_data = np.asarray(self.ucnobj.get_alldata(), dtype=float)
            ucn_times = list(range(int(ucn_all_data.shape[0])))
        if not ucn_times:
            raise RuntimeError(f"No MT3DMS concentration timesteps found in {self.path_file}")

        def _surface_concentration(period_index: int) -> np.ndarray:
            time_index = min(period_index + 1, len(ucn_times) - 1)
            if ucn_all_data is None:
                values = np.asarray(self.ucnobj.get_data(totim=ucn_times[time_index]), dtype=float)
            else:
                values = np.asarray(ucn_all_data[time_index], dtype=float)
            surface = values[0].copy()
            surface[surface >= 1e30] = np.nan
            return surface

        self.dict_concentration_seepage = {}
        self.dict_mass_seepage = {}
        self.dict_mass_accumulated = {}

        # Boucle sur chaque pas de temps
        # for i in range(len(concobj_1c_fil)):
        for i in range(self.nper):
            the_time = str(i + 1)
            logger.info("Processing MT3DMS timestep %d/%d", i + 1, self.nper)

            do_export_tif = True
            if not export_all_tif:
                if i > 0:
                    do_export_tif = False

            seep = self.outflow_drain[i]

            if concentration_seepage:
                concobj_1c_fil_surf = _surface_concentration(i)
                # concobj_1c_fil_surf = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf)
                concobj_1c_fil_surf[seep <= 0] = -9999
                concobj_1c_fil_surf[self.inactive_mask] = -9999

                output_path = self.tifs_file + "/concentration_seepage_t(" + the_time + ").tif"
                if do_export_tif:
                    export_tif(
                        self.dem_watershed_path,
                        concobj_1c_fil_surf,
                        output_path,
                        -9999,
                    )
                self.dict_concentration_seepage[i] = concobj_1c_fil_surf

            if mass_seepage:
                massobj_1c_fil_surf = _surface_concentration(i)
                # massobj_1c_fil_surf = np.ma.masked_where(seep <= 0, massobj_1c_fil_surf)
                massobj_1c_fil_surf[seep <= 0] = np.nan
                massobj_1c_fil_surf = (
                    massobj_1c_fil_surf * seep
                )  # mg/l to kg/m3 ==> kg/m3 * m3/d ==> kg/d
                massobj_1c_fil_surf[self.inactive_mask] = -9999
                massobj_1c_fil_surf = np.where(
                    np.isnan(massobj_1c_fil_surf), -9999, massobj_1c_fil_surf
                )

                output_path = self.tifs_file + "/mass_seepage_t(" + the_time + ").tif"
                if do_export_tif:
                    export_tif(
                        self.dem_watershed_path,
                        massobj_1c_fil_surf,
                        output_path,
                        -9999,
                    )
                self.dict_mass_seepage[i] = massobj_1c_fil_surf

            if mass_accumulated:
                accumulated_mass = masstransfer.Masstransfer(
                    geographic,
                    "mass_seepage_t(" + the_time + ").tif",
                    "tracept_conc_t(" + the_time + ").shp",
                    "mass_accumulated_t(" + the_time + ").tif",
                    extraction_folder=self.save_file,
                    routing_fill_path=self.routing_fill_path,
                    routing_direc_path=self.routing_direc_path,
                )
                accumulated_mass.trace_cumulated()
                output_path = self.tifs_file + "/mass_accumulated_t(" + the_time + ").tif"
                with rasterio.open(output_path) as src:
                    self.dict_mass_accumulated[i] = src.read(1)

        # concobj_1c_fil_surf = dict(list(concobj_1c_fil_surf.items())[:])

        if concentration_seepage:
            logger.info(
                "Exported concentration seepage: %d timesteps", len(self.dict_concentration_seepage)
            )

        if mass_seepage:
            logger.info("Exported mass seepage: %d timesteps", len(self.dict_mass_seepage))

        if mass_accumulated:
            logger.info("Exported accumulated mass: %d timesteps", len(self.dict_mass_accumulated))

        close = getattr(self.ucnobj, "close", None)
        if callable(close):
            close()


# %% ---- NOTES
logger = get_logger(__name__)


# The river drops its vertical grille: an MT3DMS deck never reads one.
def _only_upstream(upstream: tuple[SolverRun, ...], adapter_name: str) -> SolverRun:
    """Return the one upstream run the adapter follows, or say what the plan declared."""
    if len(upstream) != 1:
        names = ", ".join(
            sorted(
                {
                    str(
                        getattr(run, "slot", None)
                        and getattr(run.slot, "name", None)
                        or getattr(run, "id", run)
                    )
                    for run in upstream
                }
            )
        )
        raise SolverInputError(
            f"Transport '{adapter_name}' follows exactly one flow run, and the plan "
            f"declares {len(upstream)} of them ({names or 'none'})."
        )
    return upstream[0]


def _concentration_parameters(options: BaseModel | None) -> dict[str, object]:
    """Flatten the validated ``[transport.mt3dms]`` table to its parameter values."""
    if options is None:
        return {}
    return dict(options.model_dump())


def _with_maybe_slot(slot: RunSlot | None, default_folder: str, default_name: str) -> RunSlot:
    """Return ``slot`` unchanged, or a slot that names a folder of its own."""
    return slot if slot is not None else RunSlot(folder=default_folder, name=default_name)


class Mt3dmsTransportAdapter:
    """Adapter for ``transport/mt3dms`` runs, beside its engine class.

    A transport run follows one flow run through its ``requires`` edge and
    reads the validated ``[transport.mt3dms]`` table through ``options``. Its
    build takes the ``Model`` of that flow from ``upstream[0]``, and no setup,
    no plan and no store is read during a solve: the solute name, the
    parameter values, the working folder and the solver binary are the facts
    the arguments give.

    The stored concentration keeps one path per solute, under
    ``concentration/``, with the species name the run carries. The suffix of
    the deck is a constant of the adapter, ``_mt_s1``, so a resumed plan
    rebuilds the same files without reading an index anywhere.
    """

    name: ClassVar[str] = "mt3dms"
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    geometry: ClassVar[str] = "raster"
    writes: ClassVar[tuple[str, ...]] = ("concentration/*",)
    reads: ClassVar[tuple[str, ...]] = (FACE_FLOW,)
    supports: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type[BaseModel] | None] = ConcentrationTransportParametersConfig
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow_nwt"),)
    SUFFIX: ClassVar[str] = "_mt_s1"

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """Refuse a solute name that an output name cannot carry.

        ``spc_name`` names the solute stored under ``concentration/``. An
        empty name points at a group without a variable, and a name with a
        separator escapes the group into other variables of the run, so the
        refusal says both rules in one sentence.
        """
        if options is not None:
            name = getattr(options, "spc_name", None)
            if name is None or not str(name).strip() or "/" in str(name):
                raise SolverInputError(
                    f"[transport.mt3dms] spc_name = {name!r} is not a solute name: "
                    "write the name of one solute, without a separator, and the "
                    f"concentration is stored at concentration/{name!s}/ otherwise."
                )

    def build(
        self,
        model: Any,
        options: BaseModel | None = None,
        slot: RunSlot | None = None,
        upstream: tuple[SolverRun, ...] = (),
    ) -> SolverRun:
        """Build the MT3DMS deck of the flow run it follows, in memory.

        The solver object is the one of ``upstream[0]``, a finished
        :class:`~hydromodpy.solver.modflow_nwt.nwt.nwt_solver.ModflowNwt`.
        The folder and the base name are the slot's, and the suffix is the
        constant of this adapter, so a resumed plan rebuilds the same deck.
        The parameters of the deck come from the validated table the runner
        holds: one solute, and the scalar rates of its block.
        """
        flow_run = _only_upstream(upstream, self.name)
        if flow_run.solver_model is None:
            raise SolverInputError(
                f"Transport '{self.name}' follows a flow run whose model is missing. "
                "MT3DMS reads the NWT objects of the flow, and none was built."
            )
        suffix = str(self.SUFFIX)
        parameters = _concentration_parameters(options)
        solver_model = Mt3dms(
            domain=model.geometry.domain,
            params=parameters,
            model_modflow=flow_run.solver_model,
            model_folder=str(slot.folder) if slot is not None else "HydroModPy_outputs",
            model_name=nwt_safe_name(str(flow_run.slot.name)),
            suffix_name=suffix,
            bin_path=slot.bin_dir if slot is not None else None,
            spc_name=parameters.get("spc_name", "NO3"),
        )
        solver_model.raster = get_raster(model)
        solver_model.pre_processing()
        return SolverRun(
            slot=_with_maybe_slot(
                slot, str(solver_model.model_folder), nwt_safe_name(str(flow_run.slot.name))
            ),
            model=flow_run.model,
            options=options,
            solver_model=solver_model,
        )

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Write the MT3DMS input files, solve, and return the solved run."""
        solver_model = solver_run.solver_model
        success = solver_model.processing(
            write_model=not solver_run.written, run_model=True, verbose=True
        )
        if not success:
            raise SolverDivergedError(
                f"[HMPY.E401] Transport solver '{self.name}' failed for run "
                f"'{solver_run.slot.name}'. "
                f"See {getattr(solver_model, 'full_path', '<unknown>')} for diagnostics."
            )
        return replace(
            solver_run,
            output_dir=Path(solver_model.full_path),
            written=True,
            solved=True,
        )

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the ``concentration/<spc_name>`` fields of a solved run."""
        extractors.create(self.process_type, self.name).extract(solver_run, store, retention)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch directory written by this run, if any."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)
