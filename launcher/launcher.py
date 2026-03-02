"""HydroModPyLauncher — HydroModPy pipeline orchestrator.

This module is the single entry point of the hydrogeological modelling
pipeline. It runs five phases sequentially, each of which can be
instrumented through user-defined hooks.

Pipeline
--------
1. **Setup**
   Initialises the structural objects of the model from ``config.toml``:
   workspace (input/output folders), geographic context (projection, extent,
   DEM), simulation domain (MODFLOW grid, optional geology), and the flow
   and transport configuration objects.

2. **Data**
   Loads external forcings that are independent of the solver:

   - *Climatic*: rainfall and PET time series (``Climatic``).
   - *Oceanic*: mean sea level (MSL) downloaded from the SHOM tide-gauge
     service (``fetch_msl_or_default``). If the network is unavailable, the
     fallback value 0.0 m is used silently. When an ``ocean`` boundary
     condition is declared in the config, the MSL is automatically injected
     into it.

3. **Flow**
   Builds and runs the groundwater flow model:

   - Solver selection: MODFLOW-NWT (Newton-Raphson, suited to unconfined
     aquifers) or MODFLOW 6, driven by ``[solver] solver_engine``.
   - Pre-processing: FloPy grid construction, hydraulic parameter assignment
     (K, Sy), boundary conditions (drains, recharge, prescribed head).
   - MODFLOW binary execution.
   - Post-processing, conditional on solver convergence: water-table
     elevation, depth to water table, seepage areas, drain fluxes, monthly
     intermittency index.
   - Pickle dump of the pre-processed model object for standalone
     post-processing or manual inspection.

4. **Particles** *(MODFLOW-NWT only)*
   Lagrangian particle tracking with MODPATH:

   - Computation of flow pathlines from source points (drains, outlets).
   - Export of pathlines and final particle positions as shapefiles.
   - Filtering by travel time, flux magnitude, seepage zones, and
     inflow/outflow direction.

5. **Transport**
   Advective-dispersive solute transport simulation:

   - MT3DMS coupled to MODFLOW-NWT, or MODFLOW 6-GWT, depending on the
     selected solver.
   - Uses the velocity field produced by the Flow phase as hydrodynamic
     forcing.

Hooks
-----
A ``hooks.py`` file placed in the same directory as ``config.toml`` is
automatically discovered and loaded. It may define any of the following
functions, called immediately before and after each phase:

.. code-block:: python

    def on_before_setup(result): ...
    def on_after_setup(result): ...
    def on_before_data(result): ...
    def on_after_data(result): ...
    def on_before_flow(result): ...
    def on_after_flow(result): ...
    def on_before_particles(result): ...
    def on_after_particles(result): ...
    def on_before_transport(result): ...
    def on_after_transport(result): ...

Usage
-----
::

    from launcher import HydroModPyLauncher

    result = HydroModPyLauncher("path/to/config.toml").run()

Or from the command line::

    python -m launcher run path/to/config.toml

Environment variables
---------------------
``HYDROMODPY_OUT_PATH``
    Overrides the output path defined in ``config.toml``.
    Useful for redirecting results in CI pipelines or on HPC clusters
    without editing the configuration file.
"""

from __future__ import annotations

import os
import pickle
import tomllib
from pathlib import Path

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data_managers import DataManagers
from hydromodpy.data_managers.geology.geology_field import GeologyField
from hydromodpy.data_managers.oceanic import Oceanic
from hydromodpy.domain import Domain
from hydromodpy.process import Flow, Transport
from hydromodpy.solver import SolverEngine
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    Modpath,
    Mt3dms,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport
from hydromodpy.watershed.climatic import Climatic
from hydromodpy.watershed.settings import Settings
from launcher.hook_registry import HookRegistry
from launcher.run_result import RunResult


class HydroModPyLauncher:
    """Orchestrates the HydroModPy pipeline driven by a TOML configuration file.

    Parameters
    ----------
    config_path : str | Path
        Path to the ``config.toml`` file.  A ``hooks.py`` placed in the same
        directory is automatically discovered and loaded.
    """

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.cfg = HydroModPyConfig.from_toml(self.config_path)

        # HYDROMODPY_OUT_PATH allows redirecting outputs without editing
        # config.toml (useful in CI pipelines or on HPC clusters).
        if out_path_env := os.environ.get("HYDROMODPY_OUT_PATH"):
            self.cfg.workspace.out_dir_path = Path(out_path_env)

        with self.config_path.open("rb") as fh:
            raw_toml = tomllib.load(fh)

        self.result = RunResult(cfg=self.cfg, config_path=self.config_path, raw_toml=raw_toml)
        self.hooks  = HookRegistry.discover(self.config_path)

    def run(self) -> RunResult:
        """Execute the full pipeline and return the populated result object."""
        r   = self.result
        cfg = self.cfg

        # ── Setup ─────────────────────────────────────────────────────────────
        # Initialise the structural model objects: workspace, geographic
        # context, domain (grid + optional geology), flow and transport config.
        self.hooks.call("on_before_setup", r)

        r.workspace  = hmp.Workspace(config=cfg.workspace)
        r.geographic = hmp.Geographic(cfg.geographic, r.workspace)
        surface_topo = r.geographic.get_domain_surface_topo()
        ws           = r.workspace

        r.domain = Domain(config=cfg.domain, surface_topo=surface_topo)
        if "geology" in DataManagers.from_config(cfg.data).types:
            # Geology is optional: loaded only when [data.geology] is present
            # in config.toml.
            geology = GeologyField.from_watershed_config(
                cfg.data.geology, raster_support=surface_topo.support
            )
            r.domain.set_zone("geology", geology)

        r.flow      = Flow(config=cfg.flow)
        r.settings  = Settings()
        r.transport = Transport(config=cfg.transport)

        self.hooks.call("on_after_setup", r)

        # ── Data ──────────────────────────────────────────────────────────────
        # Load external forcings: climatic time series and mean sea level.
        # MSL is fetched from the SHOM tide-gauge service; falls back to
        # 0.0 m if the network is unavailable.
        self.hooks.call("on_before_data", r)

        r.climatic = Climatic(out_path=ws.catch_folder)

        oceanic = Oceanic()
        oceanic.extract_local_data(
            out_path=ws.catch_folder,
            geographic=r.geographic,
            oceanic_path=cfg.workspace.data_path,
        )
        oceanic.update_MSL(oceanic.fetch_msl_or_default(r.geographic))
        r.oceanic = oceanic

        # Inject MSL into the ocean boundary condition when one is declared
        # in the config (boundary_conditions.ocean).
        if "ocean" in r.flow.boundary_conditions:
            r.flow.boundary_conditions["ocean"].value = oceanic.MSL

        self.hooks.call("on_after_data", r)

        # ── Flow ──────────────────────────────────────────────────────────────
        # Build, pre-process, run and post-process the groundwater flow model
        # (MODFLOW-NWT or MODFLOW 6, depending on solver_engine).
        self.hooks.call("on_before_flow", r)

        preprocess_options = ModflowPreprocessOptions(
            box=r.settings.box,
            sink_fill=r.settings.sink_fill,
            check_grid=r.settings.check_grid,
            plot_cross=r.settings.plot_cross,
            cross_ylim=tuple(r.settings.cross_ylim) if r.settings.cross_ylim else None,
        )

        if cfg.solver.solver_engine == SolverEngine.MODFLOW_NWT:
            model_modflow = Modflow(
                r.geographic,
                model_folder=ws.simulations_folder,
                model_name=r.settings.model_name,
                bin_path=ws.bin_path,
                modflow_config=cfg.modflownwt,
                preprocess_options=preprocess_options,
            )
        else:
            model_modflow = Modflow6(
                r.geographic,
                model_folder=ws.simulations_folder,
                model_name=r.settings.model_name,
                bin_path=ws.bin_path,
                modflow_config=cfg.modflow6,
                preprocess_options=preprocess_options,
            )

        model_modflow.pre_processing(flow=r.flow, domain=r.domain, options=preprocess_options)

        # Persist the pre-processed model object to allow standalone
        # post-processing or manual inspection after the run.
        pickle_path = (
            Path(ws.simulations_folder)
            / r.settings.model_name
            / f"results_{r.settings.model_name}.pkl"
        )
        with open(pickle_path, "wb") as fh:
            pickle.dump(
                {"list_model_name": [r.settings.model_name],
                 "list_model_modflow": [model_modflow]},
                fh,
            )

        success = model_modflow.processing(
            options=ModflowRunOptions(write_model=True, run_model=True, link_mt3dms=True)
        )
        if success:
            # Post-processing is conditional on solver convergence.
            model_modflow.post_processing(
                options=ModflowPostprocessOptions(
                    watertable_elevation=True,
                    watertable_depth=True,
                    seepage_areas=True,
                    outflow_drain=True,
                    accumulation_flux=True,
                    intermittency_monthly=True,
                )
            )
        r.model_modflow = model_modflow

        self.hooks.call("on_after_flow", r)

        # ── Particles ─────────────────────────────────────────────────────────
        # Lagrangian particle tracking with MODPATH (NWT only).
        # Computes travel times and capture zones from drain/outlet sources.
        self.hooks.call("on_before_particles", r)

        if cfg.solver.solver_engine == SolverEngine.MODFLOW_NWT:
            model_modpath = Modpath(
                r.domain,
                r.transport,
                model_modflow,
                model_folder=ws.simulations_folder,
                model_name=model_modflow.model_name,
                bin_path=ws.bin_path,
            )
            model_modpath.pre_processing()
            model_modpath.processing(write_model=True, run_model=True)
            model_modpath.post_processing(
                model_modpath,
                ending_point=True,
                starting_point=True,
                pathlines_shp=True,   # pathlines exported as shapefile
                particles_shp=True,   # final particle positions as shapefile
                random_id=None,
            )
            model_modpath.filt_processing(
                model_modpath,
                norm_flux=True,       # normalise by drained flux
                filt_time=True,       # filter by travel time
                filt_seep=True,       # filter by seepage zone
                filt_inout=True,      # filter by inflow/outflow direction
                calc_rtd=False,       # residence-time distribution (disabled)
                random_id=None,
            )
            r.model_modpath = model_modpath

        self.hooks.call("on_after_particles", r)

        # ── Transport ─────────────────────────────────────────────────────────
        # Advective-dispersive solute transport (MT3DMS or MODFLOW 6-GWT).
        # Uses the flow-phase velocity field as hydrodynamic forcing.
        self.hooks.call("on_before_transport", r)

        if cfg.solver.solver_engine == SolverEngine.MODFLOW_NWT:
            model_transport = Mt3dms(
                r.domain,
                r.transport,
                model_modflow,
                model_folder=ws.simulations_folder,
                model_name=model_modflow.model_name,
                suffix_name="_mt_s1",  # suffix identifying the transport scenario
                bin_path=ws.bin_path,
            )
        else:
            model_transport = Modflow6Transport(
                r.domain,
                r.transport,
                model_modflow,
                model_folder=ws.simulations_folder,
                model_name=model_modflow.model_name,
                suffix_name="_mt_s1",
            )
        model_transport.pre_processing()
        model_transport.processing(write_model=True, run_model=True, verbose=True)
        model_transport.post_processing(model_transport)
        r.model_transport = model_transport

        self.hooks.call("on_after_transport", r)

        return r
