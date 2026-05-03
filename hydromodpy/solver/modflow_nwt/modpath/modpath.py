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

from __future__ import annotations

import io
import os
from collections.abc import Mapping
from contextlib import redirect_stdout

import flopy
import flopy.utils.binaryfile as fpu

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.contracts import Solver
from hydromodpy.solver.modflow_common import ensure_solver_binary

from ._filt_processing import filter_pathlines
from ._post_processing import write_shapefiles
from ._pre_processing import (
    attach_starting_locations,
    build_modpath_model,
    compute_seepage_zone,
    load_modflow_for_modpath,
)
from ._resolvers import (
    get_geographic,
    resolve_crs_proj,
    resolve_domain_raster,
    resolve_seepage_clip_raster,
    resolve_watershed_shp,
    resolve_zone_partic,
)

logger = get_logger(__name__)


class Modpath(Solver):
    """Particle tracking driver coordinating MODPATH-6 around a MODFLOW-NWT run."""

    def __init__(
        self,
        domain: object,
        transport: object,
        model_modflow: object | None = None,
        # Workflow settings
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default_modpath",
        bin_path: str | None = None,
        # Specific settings
        zone_partic: str | None = None,
        track_dir: str | None = None,
        bore_depth: list | None = None,
        cell_div: int | None = None,
        zloc_div: bool | None = None,
        sel_random: int | None = None,
        sel_slice: int | None = None,
    ) -> None:
        """Configure the MODPATH driver from a paired MODFLOW-NWT model."""
        if model_modflow is None:
            raise ValueError("model_modflow must be provided to initialize Modpath")
        if not hasattr(model_modflow, "mf"):
            raise ValueError(
                "Modpath is available only with MODFLOW-NWT flow models. "
                "Please set [solver].solver_engine = 'modflownwt' and run modflownwt first."
            )

        self.domain = domain
        self.transport = transport
        self.model_modflow = model_modflow
        self.geographic = get_geographic(model_modflow)
        self.model_name = model_name
        self.model_folder = model_folder
        self.full_path = os.path.join(model_folder, model_name)

        if not os.path.isdir(self.full_path):
            raise FileNotFoundError(f"Directory not found: {self.full_path}")
        self.exe = str(ensure_solver_binary("mp6", bin_path))

        particle_params: dict = {}
        raw_params = getattr(transport.modpath, "parameters", None)
        if isinstance(raw_params, Mapping):
            particle_params = dict(raw_params)

        def _pick(key: str, explicit: object, default: object) -> object:
            if explicit is not None:
                return explicit
            return particle_params.get(key, default)

        zone_partic_val = _pick("zone_partic", zone_partic, "domain")
        self.zone_partic = resolve_zone_partic(
            zone_partic_val,
            full_path=self.full_path,
            model_modflow=self.model_modflow,
        )

        self.track_dir = _pick("track_dir", track_dir, "forward")
        self.bore_depth = _pick("bore_depth", bore_depth, None)
        self.cell_div = _pick("cell_div", cell_div, 1)
        self.zloc_div = _pick("zloc_div", zloc_div, False)
        self.sel_random = _pick("sel_random", sel_random, None)
        self.sel_slice = _pick("sel_slice", sel_slice, None)

        self.verbose = False
        self.check = False

        self.simfile_ext = "mpsim"
        self.namefile_ext = "mpnam"
        self.version = "modpath"

        # default forward, can be "backward" or "custom"
        self.track = 1
        self.zone_opt = 1
        self.zone_inj = 1

        self.simulation_type = 2
        self.weak_sink_option = 1
        self.weak_source_option = 1
        self.reference_time_option = 1
        self.stop_option = 2
        self.particle_generation_option = 2
        self.time_point_option = 1
        self.budget_output_option = 1
        self.retardation_option = 1
        self.advective_observations_option = 1

        self.group_placement = [[1, 1, 1, 0, 1, 1]]
        self.stop_zone = 1

        self.input_style = 1
        self.def_face_ct = 0

        self.starting_point = True
        self.ending_point = True
        self.pathlines_shp = True
        self.particles_shp = True

        self.norm_flux = False
        self.filt_time = True
        self.filt_seep = True
        self.filt_inout = True
        self.calc_rtd = True
        self.random_id = None

    def _get_geographic(self) -> object | None:
        return get_geographic(self.model_modflow)

    def _get_crs_proj(self) -> object | None:
        return resolve_crs_proj(self.model_modflow, self.domain)

    def _resolve_domain_raster(self) -> str:
        return resolve_domain_raster(self.model_modflow)

    def _resolve_seepage_clip_raster(self) -> str:
        return resolve_seepage_clip_raster(
            full_path=self.full_path,
            model_modflow=self.model_modflow,
        )

    def _get_watershed_shp(self) -> str | None:
        return resolve_watershed_shp(self.model_modflow)

    def pre_processing(self) -> None:
        """Build the MODPATH input deck from a finished MODFLOW-NWT run."""
        self.mf = load_modflow_for_modpath(
            full_path=self.full_path,
            model_name=self.model_name,
            model_modflow=self.model_modflow,
            verbose=self.verbose,
            check=self.check,
        )
        bas = self.mf.get_package("BAS6")
        upw = self.mf.get_package("UPW")
        laytype = upw.laytyp.array
        ibound = bas.ibound.array

        self.mp = build_modpath_model(
            mf=self.mf,
            full_path=self.full_path,
            model_name=self.model_name,
            exe=self.exe,
            simfile_ext=self.simfile_ext,
            namefile_ext=self.namefile_ext,
            version=self.version,
        )

        bud_file = os.path.join(self.full_path, f"{self.model_name}.cbc")
        head_file = os.path.join(self.full_path, f"{self.model_name}.hds")
        cbb = fpu.CellBudgetFile(bud_file)
        cbb.get_data(kstpkper=(0, 0), text="DRAINS")
        cbb.get_data(kstpkper=(0, 0), text="RECHARGE")
        _ = head_file

        if self.track_dir == "forward":
            self.track = 1
            self.zone_opt = 1
            self.zone_inj = 1

        if self.bore_depth is None:
            szone = compute_seepage_zone(mf=self.mf, bud_file=bud_file)
            self.zone_opt = 2
            self.zone_inj = szone.copy()

        if self.track_dir == "backward":
            self.track = 2
            self.zone_opt = 1
            self.zone_inj = 1

        option_flags = [
            self.simulation_type,
            self.track,
            self.weak_sink_option,
            self.weak_source_option,
            self.reference_time_option,
            self.stop_option,
            self.particle_generation_option,
            self.time_point_option,
            self.budget_output_option,
            self.zone_opt,
            self.retardation_option,
            self.advective_observations_option,
        ]
        logger.debug("Option flags: %s", option_flags)
        logger.debug(
            "Modpath settings - track: %s, zone_opt: %s, zone_inj: %s",
            self.track,
            self.zone_opt,
            type(self.zone_inj),
        )

        flopy.modpath.Modpath6Sim(
            model=self.mp,
            option_flags=option_flags,
            group_placement=self.group_placement,
            stop_zone=self.stop_zone,
            zone=self.zone_inj,
        )

        self.point_data = attach_starting_locations(
            mp=self.mp,
            mf=self.mf,
            zone_partic=self.zone_partic,
            track_dir=self.track_dir,
            cell_div=self.cell_div,
            bore_depth=self.bore_depth,
            sel_random=self.sel_random,
            sel_slice=self.sel_slice,
            input_style=self.input_style,
        )

        self.poro_modpath = self.model_modflow.sy
        self.ss_modpath = self.model_modflow.ss

        flopy.modpath.Modpath6Bas(
            self.mp,
            hnoflo=self.model_modflow.bas_hnoflo,
            hdry=self.model_modflow.upw_hdry,
            def_face_ct=self.def_face_ct,
            laytyp=laytype,
            ibound=ibound,
            prsity=self.poro_modpath,
            prsityCB=self.ss_modpath,
            extension="mpbas",
            unitnumber=86,
        )

    def processing(self, write_model: bool = True, run_model: bool = False) -> bool:
        """Write input files then optionally launch the MODPATH executable."""
        if write_model:
            with redirect_stdout(io.StringIO()):
                self.mp.write_input()

        success_model = False
        if run_model:
            verbose = self.verbose
            success_model, _tempo = self.mp.run_model(silent=not verbose)
        return success_model

    def post_processing(
        self,
        model_modpath: object,
        starting_point: bool = True,
        ending_point: bool = True,
        pathlines_shp: bool = True,
        particles_shp: bool = True,
        random_id: int | None = None,
    ) -> None:
        """Write the standard MODPATH shapefile outputs."""
        self.starting_point = starting_point
        self.ending_point = ending_point
        self.pathlines_shp = pathlines_shp
        self.particles_shp = particles_shp

        full_path, particles_file = write_shapefiles(
            model_modpath=model_modpath,
            starting_point=starting_point,
            ending_point=ending_point,
            pathlines_shp=pathlines_shp,
            particles_shp=particles_shp,
            random_id=random_id,
        )
        self.full_path = full_path
        self.particles_file = particles_file

    def filt_processing(
        self,
        model_modpath: object,
        norm_flux: bool = False,
        filt_time: bool = True,
        filt_seep: bool = True,
        filt_inout: bool = True,
        calc_rtd: bool = True,
        random_id: int | None = None,
    ) -> None:
        """Filter MODPATH outputs and compute the residence time distribution."""
        filter_pathlines(
            modpath_runner=self,
            model_modpath=model_modpath,
            norm_flux=norm_flux,
            filt_time=filt_time,
            filt_seep=filt_seep,
            filt_inout=filt_inout,
            calc_rtd=calc_rtd,
            random_id=random_id,
        )
