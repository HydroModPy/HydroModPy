# Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
#
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License 2.0 which is available at
# http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
# which is available at https://www.apache.org/licenses/LICENSE-2.0.
#
# SPDX-License-Identifier: EPL-2.0 OR Apache-2.0

"""MODPATH particle tracking on a MODFLOW-NWT flow model.

The seepage raster that MODPATH releases particles from, ``zone_partic =
"seepage_clip"``, is built by the adapter from the head file of the flow, with the
seepage rule the run store derives, and never by a read of the store during the solve.
The historical TIFF maps and the MODPATH post-processing are in
``hydromodpy_annex/solver/nwt_postprocess/`` and
``hydromodpy_annex/solver/modpath_post/``, because no adapter calls them.
"""

from __future__ import annotations

import io
import os
from collections.abc import Mapping
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import flopy
import numpy as np
from pydantic import BaseModel

from hydromodpy.core.budget.flux import first_finite_layer, seepage_mask
from hydromodpy.core.exceptions import ConfigError, SolverDivergedError, SolverInputError
from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.core.logging import get_logger
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.transport.transport_config import ModpathParametersConfig
from hydromodpy.results.field_registry import FACE_FLOW
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.calibration_extractors import open_cell_budget
from hydromodpy.solver.modflow_common.flow_run import nwt_safe_name
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt

from ._pre_processing import (
    attach_starting_locations,
    budget_holds,
    build_modpath_model,
    compute_seepage_zone,
    load_modflow_for_modpath,
)
from .resolvers import (
    get_catchment,
    get_raster,
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
        domain: Domain,
        params: Mapping[str, object] | None = None,
        model_modflow: ModflowNwt | None = None,
        # Workflow settings
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default_modpath",
        bin_path: str | os.PathLike[str] | None = None,
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
                "Please set solver.backend = 'modflow_nwt' and run modflow_nwt first."
            )

        self.domain = domain
        self.params = dict(params or {})
        self.model_modflow = model_modflow
        self.model_name = model_name
        self.model_folder = model_folder
        self.full_path = os.path.join(model_folder, model_name)

        if not os.path.isdir(self.full_path):
            raise FileNotFoundError(f"Directory not found: {self.full_path}")
        self.exe = str(ensure_solver_binary("mp6", bin_path))

        particle_params: dict = dict(self.params)

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


def _only_upstream(upstream: tuple[SolverRun, ...], adapter_name: str) -> SolverRun:
    """Return the one upstream run the adapter follows, or say what the plan declared."""
    if len(upstream) != 1:
        names = ", ".join(
            sorted(
                {
                    name
                    for name in (
                        getattr(getattr(run, "slot", None), "name", None) or getattr(run, "id", "")
                        for run in upstream
                    )
                    if name
                }
            )
        )
        raise SolverInputError(
            f"Transport '{adapter_name}' follows exactly one flow run, and the plan "
            f"declares {len(upstream)} of them ({names or 'none'})."
        )
    return upstream[0]


def _particle_parameters(options: BaseModel | None) -> dict[str, object]:
    """Flatten the validated ``[transport.modpath]`` table to its parameter values."""
    if options is None:
        return {}
    return dict(options.model_dump())


def _wants_seepage_clip(parameters: Mapping[str, object]) -> bool:
    """Return True when the release zone asks for the seepage areas of the flow.

    The value is read on the parameters as declared, before the engine
    resolves the alias to a raster path.
    """
    return str(parameters.get("zone_partic", "domain")) == "seepage_clip"


def _with_maybe_slot(slot: RunSlot | None, default_folder: str, default_name: str) -> RunSlot:
    """Return ``slot`` unchanged, or a slot that names a folder of its own."""
    return slot if slot is not None else RunSlot(folder=default_folder, name=default_name)


def _write_seepage_clip_raster(flow_run: SolverRun) -> None:
    """Derive the seepage raster of the flow run it follows from its own heads.

    The rule is the one the run store derives the ``seepage_mask`` field with:
    the water table stands in the highest layer that holds a finite head, and a
    cell seeps when it reaches ``topography - band_depth / 2``, with the drain
    band the flows carry in ``Model.options.drain_band_depth_m``. The raster is
    written early, beside the flow deck, in the folder the release zone reads,
    and is rebuilt at every build: a raster left behind by an earlier run of
    the same project is never an input of this one.
    """
    flow = flow_run.solver_model
    flow_dir = (
        Path(flow_run.output_dir) if flow_run.output_dir is not None else Path(str(flow.full_path))
    )
    reference = getattr(flow, "dem_watershed_path", None)
    if reference is None:
        raise SolverInputError(
            "zone_partic = 'seepage_clip' needs the topography raster the flow run wrote "
            "on its solver grid, and the run it follows does not declare one."
        )
    raster_path = flow_dir / "_postprocess" / "_rasters" / "seepage_areas_t(0).tif"
    raster_path.parent.mkdir(parents=True, exist_ok=True)

    name = str(flow_run.slot.name)
    model_name = getattr(flow, "model_name", None) or nwt_safe_name(name)
    heads_path = flow_dir / f"{model_name}.hds"
    if not heads_path.is_file():
        raise SolverInputError(
            f"zone_partic = 'seepage_clip' reads the heads of the flow run it follows, "
            f"and {heads_path} does not exist."
        )
    hds = flopy.utils.binaryfile.HeadFile(str(heads_path))
    try:
        heads = np.asarray(hds.get_data(totim=hds.get_times()[0]), dtype="float64")
    finally:
        hds.close()

    # The dry and the inactive sentinels are finite numbers, so they leave the
    # array as not-a-number before the water table is read off the layers.
    sentinels = [
        float(value)
        for value in (getattr(flow, "bas_hnoflo", None), getattr(flow, "upw_hdry", None))
        if value is not None
    ]
    dead = np.zeros(heads.shape, dtype=bool)
    for sentinel in sentinels:
        dead |= np.isclose(heads, sentinel)
    dead |= ~np.isfinite(heads)
    heads = np.where(dead, np.nan, heads)

    # The heads read (layer, row, col); the rule of the store reads (time, layer, cell).
    watertable = first_finite_layer(heads.reshape(1, heads.shape[0], -1))[0]
    model_options = getattr(flow_run.model, "options", None)
    band = float(getattr(model_options, "drain_band_depth_m", 0.0) or 0.0)
    topography = np.asarray(getattr(flow, "top_elevation", None), dtype="float64").reshape(-1)
    mask = seepage_mask(watertable=watertable.reshape(-1), topography=topography, band_depth=band)

    shape = (int(getattr(flow, "nrow", 0)), int(getattr(flow, "ncol", 0)))
    seepage = np.asarray(mask, dtype="float64").reshape(shape)
    export_tif(str(reference), seepage, str(raster_path), -9999.0)
    logger.info("Rebuilt the seepage raster of run %s at %s", name, raster_path)


class ModpathTransportAdapter:
    """Adapter for ``transport/modpath`` runs, beside its engine class.

    A transport run follows one flow run through its ``requires`` edge and
    reads the validated ``[transport.modpath]`` table through ``options``. Its
    build takes the ``Model`` of that flow from ``upstream[0]`` and the
    finished MODFLOW-NWT solver of that run. Same folder, same base name, no
    suffix: the deck carries the name of the flow model it reads its heads
    and budget from.

    The release zone stays solver-side. When ``zone_partic`` asks for the
    seepage areas, the build derives the raster from the heads of the flow
    run before the engine resolves the alias, so no store is read during a
    solve.
    """

    name: ClassVar[str] = "modpath"
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    geometry: ClassVar[str] = "raster"
    writes: ClassVar[tuple[str, ...]] = (
        "particles/x",
        "particles/y",
        "particles/z",
        "particles/time",
        "particles/endpoint_x",
        "particles/endpoint_y",
        "particles/endpoint_z",
        "particles/endpoint_time",
    )
    reads: ClassVar[tuple[str, ...]] = (FACE_FLOW,)
    supports: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type[BaseModel] | None] = ModpathParametersConfig
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow_nwt"),)

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """Check the release zone the deck will read, before anything is written.

        The alias resolution runs on the engine at build time, and a release
        zone asking for the seepage areas needs the heads of the flow. Nothing
        here reads them: the refusal of a flow run without its head file stays
        at the build, which knows the folder and the name it reads.
        """
        if options is not None:
            zone = getattr(options, "zone_partic", None)
            if zone is None or not str(zone).strip():
                raise SolverInputError(
                    "[transport.modpath] zone_partic is empty: write 'domain', "
                    "'seepage_clip', or the path of a raster that marks the "
                    "release cells."
                )

    def build(
        self,
        model: Any,
        options: BaseModel | None = None,
        slot: RunSlot | None = None,
        upstream: tuple[SolverRun, ...] = (),
    ) -> SolverRun:
        """Build the MODPATH deck of the flow run it follows, in memory.

        The solver object is the one of ``upstream[0]``, a finished
        :class:`~hydromodpy.solver.modflow_nwt.nwt.nwt_solver.ModflowNwt`. The
        folder and the base name are the slot's, with no suffix, so the deck
        reads the heads and the budget of the flow run in place. The release
        zone is resolved on the engine, and ``seepage_clip`` has its raster
        derived from the flow run first.
        """
        flow_run = _only_upstream(upstream, self.name)
        if flow_run.solver_model is None:
            raise SolverInputError(
                f"Transport '{self.name}' follows a flow run whose model is missing. "
                "MODPATH reads the NWT objects and files of the flow, and none was built."
            )
        parameters = _particle_parameters(options)
        if _wants_seepage_clip(parameters):
            _write_seepage_clip_raster(flow_run)
        solver_model = Modpath(
            model.geometry.domain,
            params=parameters,
            model_modflow=flow_run.solver_model,
            model_folder=str(slot.folder) if slot is not None else "HydroModPy_outputs",
            model_name=nwt_safe_name(str(flow_run.slot.name)),
            bin_path=slot.bin_dir if slot is not None else None,
        )
        solver_model.raster = get_raster(model)
        solver_model.catchment = get_catchment(model)
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
        """Write the MODPATH input files, solve, and return the solved run.

        The legacy post-processing and filtering stay with the annex: the
        extractor reads pathlines and endpoints into the run store, and no
        shapefile is written by this run.
        """
        solver_model = solver_run.solver_model
        success = solver_model.processing(write_model=not solver_run.written, run_model=True)
        if not success:
            raise SolverDivergedError(
                f"[HMPY.E401] Transport solver '{self.name}' failed for run "
                f"'{solver_run.slot.name}'. "
                f"See {getattr(solver_model, 'full_path', '<unknown>')} for diagnostics."
            )
        return replace(
            solver_run,
            output_dir=Path(solver_model.full_path) if hasattr(solver_model, "full_path") else None,
            written=True,
            solved=True,
        )

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the pathlines and endpoints of a solved run through its registered extractor."""
        extractors.create(self.process_type, self.name).extract(solver_run, store, retention)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch directory written by this run, if any."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)
