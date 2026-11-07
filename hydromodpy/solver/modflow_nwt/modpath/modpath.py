# Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
#
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License 2.0 which is available at
# http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
# which is available at https://www.apache.org/licenses/LICENSE-2.0.
#
# SPDX-License-Identifier: EPL-2.0 OR Apache-2.0

"""MODPATH particle tracking on a MODFLOW-NWT flow model."""

from __future__ import annotations

import io
import os
from collections.abc import Mapping
from contextlib import redirect_stdout

import flopy
import numpy as np

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.base.protocols import DomainLike, FlowModelLike, TransportLike
from hydromodpy.solver.modflow_common import ensure_solver_binary
from hydromodpy.solver.modflow_common.calibration_extractors import open_cell_budget

from ._pre_processing import (
    attach_starting_locations,
    budget_holds,
    build_modpath_model,
    compute_seepage_zone,
    load_modflow_for_modpath,
)
from .resolvers import (
    get_geographic,
    resolve_crs_proj,
    resolve_domain_raster,
    resolve_seepage_clip_raster,
    resolve_watershed_shp,
    resolve_zone_partic,
)

logger = get_logger(__name__)


class Modpath:
    """Particle tracking driver around a completed MODFLOW-NWT run.

    ``Modpath`` builds a MODPATH-6 input deck from the paired groundwater flow
    model, resolves particle starting zones, runs pathline tracking, filters
    results, and exports shapefiles for post-processing.

    A finished ``ModflowNwt`` instance must be supplied through
    ``model_modflow`` because MODPATH reuses the MODFLOW grid, head file, and
    cell-by-cell budget.
    """

    def __init__(
        self,
        domain: DomainLike,
        transport: TransportLike,
        model_modflow: FlowModelLike | None = None,
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
        """Configure particle tracking from a paired MODFLOW-NWT model.

        Parameters select the working folder, executable location, tracking
        direction, particle zone, bore depth, cell subdivision, and optional
        random or slice-based particle selection.
        """
        if model_modflow is None:
            raise ValueError("model_modflow must be provided to initialize Modpath")
        if not hasattr(model_modflow, "mf"):
            raise ValueError(
                "Modpath is available only with MODFLOW-NWT flow models. "
                "Please set [solver.backend].backend = 'modflow_nwt' and run modflow_nwt first."
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
        if self.track_dir not in ("forward", "backward"):
            # The starting locations are populated for these two only.
            raise ConfigError(
                f"MODPATH track_dir = {self.track_dir!r} gives no starting location, so "
                "no particle would be released. Write 'forward' or 'backward', and mark "
                "the release cells with zone_partic."
            )
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
        cbb = open_cell_budget(bud_file)  # NWT ecrit en simple, MF6 en double
        if not budget_holds(cbb, "RECHARGE"):
            raise ConfigError(
                "MODPATH weighs its particles by the recharge, and this run has none: add "
                "[flow.sinks_sources.recharge]."
            )
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
        without_porosity = int(np.sum((np.asarray(self.poro_modpath) <= 0.0) & (ibound != 0)))
        if without_porosity:
            raise ConfigError(
                f"MODPATH takes its porosity from the specific yield, and Sy is zero on "
                f"{without_porosity} active cells, so the particle velocity is undefined: "
                'declare it with "Sy" in flow.param_list and [flow.param.Sy.field].'
            )

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
