# -*- coding: utf-8 -*-
"""Study-specific hooks for ``examples/example12launcher``.

The launcher discovers this file next to ``config.toml`` and imports any
function named ``on_before_<phase>`` or ``on_after_<phase>``. Each hook
receives the shared :class:`launchers.RunResult` instance and mutates it
in-place. The launcher owns object creation and solver execution; this file only
injects the parts that are specific to Example 12.

Execution model
---------------
The hook names in this file map to two kinds of lifecycle events:

- ``setup`` and ``data`` are launcher phases executed exactly once.
- ``flow`` and ``transport`` are process families executed by
  ``SimulationRunner``. Their hooks fire once per contiguous process-family
  block, not once per solver.

That distinction matters for state interpretation:

- ``on_before_flow`` prepares inputs shared by every flow solver in the block.
- ``on_after_flow`` sees ``result.model_modflow`` set to the last flow model
  executed in that block.
- ``on_before_transport`` runs before the first transport solver and therefore
  relies on the already-produced flow outputs.
- ``on_after_transport`` runs after the last transport solver and sees the final
  values of ``result.model_modpath`` and ``result.model_transport``.

This file intentionally does not recreate the generic launcher boilerplate
(workspace, geographic context, domain, solver instances, etc.). Those objects
already exist on ``RunResult`` when the relevant hook is called.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hydromodpy.display import (
    display_options_from_raw_toml,
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)
from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig
from launchers import RunResult


def on_after_data(result: RunResult) -> None:
    """Load the shared external datasets required by the study.

    This hook extends the generic launcher ``data`` phase. At this point the
    launcher has already created:

    - ``result.workspace``
    - ``result.geographic``
    - ``result.flow``
    - ``result.climatic``
    - ``result.oceanic``

    The hook adds the study assets that are not part of the generic core:

    - Naizin-specific hydrography
    - intermittency observations
    - optional hydrometry station exports driven by ``[hydrometry_stations]``
    - a one-year SAFRAN-ISBA reanalysis slice used as the raw climate source

    Notes
    -----
    ``StationSet.from_config`` can raise ``ValueError`` for invalid user
    selections or missing source data. This example treats that as a non-fatal
    warning and stores ``None`` in ``result.hydrometry`` so the rest of the run
    can continue.
    """
    from hydromodpy.data_managers.hydrometry.station_set import StationSet
    from hydromodpy.watershed import Hydrography, Intermittency

    ws = result.workspace
    data_path = result.cfg.workspace.data_path
    geo = result.geographic

    # Load the stream dataset used by the Naizin example. The shapefile is
    # located by "type" inside the configured hydro-data directory.
    result.hydrography = Hydrography(
        out_path=ws.catch_folder,
        types_obs=["botopage2024_naizin_streams_perennial-intermittent"],
        fields_obs=["FID"],
        geographic=geo,
        hydro_path=data_path,
        streams_file=None,
    )

    # Load the regional ONDE intermittency observations used for comparison in
    # downstream timeseries and diagnostics.
    result.intermittency = Intermittency(
        out_path=ws.catch_folder,
        intermittency_path=data_path,
        file_name="regional onde stations.shp",
        geographic=geo,
    )

    # The hydrometry section is custom to this example and is therefore read
    # from raw TOML rather than the validated Pydantic config tree.
    hydro_section = result.raw_toml.get("hydrometry_stations", {})
    hydro_cfg = {
        "hydrometry": {
            key: value
            for key, value in hydro_section.items()
            if key not in ["source", "selection", "output"]
        },
        "source": hydro_section.get("source", {}),
        "selection": hydro_section.get("selection", {}),
        "output": hydro_section.get("output", {}),
    }

    output_path = hydro_cfg["output"].get("path")
    if output_path:
        # Resolve relative export paths from the config file location so the
        # hook behaves the same regardless of the current working directory.
        resolved_output = Path(str(output_path)).expanduser()
        if not resolved_output.is_absolute():
            hydro_cfg["output"]["path"] = str((result.config_path.parent / resolved_output).resolve())

    if hydro_cfg["selection"].get("mode", "mask") == "mask":
        # In mask mode the example always uses the watershed polygon produced by
        # the launcher setup phase, not a hand-maintained static path.
        hydro_cfg["selection"]["mask_path"] = geo.watershed_shp

    try:
        result.hydrometry = StationSet.from_config(hydro_cfg)
    except ValueError as exc:
        print(f"Warning: Hydrometry loading failed - {exc}")
        result.hydrometry = None

    # Seed the climatic object with one transient year of observed recharge and
    # runoff. Later hooks overwrite the actual synthetic forcing used by the
    # flow model, but they still rely on these series as the initial template.
    result.climatic.update_recharge_reanalysis(
        path_file=data_path / "_climate_REANALYSIS.csv",
        clim_mod="REA",
        clim_sce="historic",
        first_year=2003,
        last_year=2003,
        time_step="ME",
        sim_state="transient",
    )
    result.climatic.update_runoff_reanalysis(
        path_file=data_path / "_climate_REANALYSIS.csv",
        clim_mod="REA",
        clim_sce="historic",
        first_year=2003,
        last_year=2003,
        time_step="ME",
        sim_state="transient",
    )


def on_before_flow(result: RunResult) -> None:
    """Prepare the shared flow inputs used by the whole flow process family.

    This hook runs once before the first flow solver in the current process
    block. If several flow solvers are declared, they all consume the same
    ``result.flow`` object configured here.

    The hook performs four tasks:

    - replace the raw reanalysis recharge by a synthetic monthly scenario
    - derive runoff from recharge
    - set study-specific model naming and preprocessing options
    - inject the final recharge policy into ``result.flow``

    The synthetic scenario is intentionally simple:

    - January, February, November, December: ``2 mm/day``
    - March, April, May, June, August, September, October: ``0 mm/day``
    - July: ``-1 mm/day`` so that evapotranspiration handling is exercised
    """
    raw_recharge = result.climatic.recharge

    # Keep the same 2003 monthly index as the reanalysis series, then overwrite
    # values with a deterministic synthetic scenario used for the example.
    synthetic_recharge = raw_recharge[
        (raw_recharge.index.year >= 2003) & (raw_recharge.index.year <= 2003)
    ] * 0
    synthetic_recharge[synthetic_recharge.index.month.isin([3, 4, 5, 6, 8, 9, 10])] = 0.0
    synthetic_recharge[synthetic_recharge.index.month.isin([1, 2, 11, 12])] = 2.0
    synthetic_recharge[synthetic_recharge.index.month.isin([7])] = -1.0
    synthetic_recharge.index = pd.to_datetime(synthetic_recharge.index)

    # Convert from mm/day (script-facing convention) to m/day
    # (solver-facing convention), then derive an arbitrary 10% runoff ratio.
    recharge = synthetic_recharge / 1000
    runoff = recharge * 0.1

    result.climatic.update_recharge(recharge, sim_state=result.flow.flow_regime)
    result.climatic.update_runoff(runoff, sim_state=result.flow.flow_regime)

    alpha = 15
    hydraulic_conductivity = 5e-5 * 24 * 3600
    specific_yield = 2 / 100

    model_version = "TRANS1"
    model_name = (
        f"{model_version}_K{hydraulic_conductivity / 24 / 3600:.1e}"
        f"_a{alpha:.1f}_Sy{specific_yield * 100:.1f}"
    )
    result.settings.update_model_name(model_name)
    result.settings.update_box_model(box=True)
    result.settings.update_sink_fill(sink_fill=False)
    result.settings.update_check_model(
        plot_cross=True,
        check_grid=True,
        cross_ylim=[0, 200],
    )

    # Reuse the policy declared in TOML for stress period 0 and negative
    # recharge handling. The time series values themselves are the synthetic
    # series computed above.
    recharge_config = result.flow.sinks_sources.get("recharge")
    first_clim = recharge_config.first_clim if recharge_config is not None else "mean"
    result.climatic.update_first_clim(first_clim)

    negative_to_evt = recharge_config.negative_to_evt if recharge_config is not None else True
    result.flow.set_recharge(
        FlowRechargeConfig(
            values=result.climatic.recharge,
            first_clim=result.climatic.first_clim,
            negative_to_evt=negative_to_evt,
        )
    )


def on_after_flow(result: RunResult) -> None:
    """Generate flow-only diagnostics after the flow process family finishes.

    This hook runs after the last contiguous flow solver. ``result.model_modflow``
    therefore points to the final flow model executed in that block, which is
    the model consumed by every post-processing call below.

    The hook:

    - builds hydrologic timeseries products
    - computes ``MatchingStreams`` diagnostics against observed hydrography
    - delegates plotting to the reusable display helpers defined by the
      ``[display]`` section of ``config.toml``
    """
    from hydromodpy.calibration.calibration_legacy.matching_stream import MatchingStreams
    from hydromodpy.modeling import timeseries

    geo = result.geographic
    ws = result.workspace
    model_modflow = result.model_modflow
    model_name = model_modflow.model_name

    timeseries.Timeseries(
        geo,
        model_modflow=model_modflow,
        runoff=result.climatic.runoff,
        model_modpath=None,
        model_mt3dms=None,
        datetime_format=True,
        subbasin_results=True,
        intermittency_weekly=False,
        intermittency_monthly=True,
        intermittency_yearly=False,
    )

    MatchingStreams(
        geo,
        result.hydrography,
        ws,
        iteration_label=model_name,
        from_calib=False,
    )

    display_options = display_options_from_raw_toml(result.raw_toml)
    plot_flow_suite(result, display_options)


def on_before_transport(result: RunResult) -> None:
    """Prepare transport inputs before the first transport solver starts.

    This hook is process-family scoped: it runs once before the transport block,
    not once per transport solver. It configures shared runtime inputs consumed
    by both particle tracking and concentration transport.

    Important assumption
    --------------------
    The hook uses ``result.model_modflow`` to locate the seepage raster and grid
    shape. Because the runner sets that attribute to the latest completed flow
    model, this example assumes that the transport block should use the last
    flow solver produced by the immediately preceding flow block.
    """
    import whitebox

    from hydromodpy.solver.modflow_nwt import Modflow

    ws = result.workspace
    flow_model = result.model_modflow
    model_name = flow_model.model_name
    sim_folder = ws.simulations_folder / model_name

    seepage_tif = sim_folder / "_postprocess/_rasters/seepage_areas_t(0).tif"
    seepage_clip_tif = sim_folder / "_postprocess/_rasters/seepage_areas_t(0)_clip.tif"

    # Clip the seepage map to the watershed polygon so Modpath can inject
    # particles only where seepage occurs inside the catchment.
    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False
    wbt.clip_raster_to_polygon(
        str(seepage_tif),
        str(ws.stable_folder / "geographic" / "watershed.shp"),
        str(seepage_clip_tif),
        maintain_dimensions=True,
    )

    modpath_params = result.cfg.transport.modpath.parameters.model_dump()
    if modpath_params.get("zone_partic") == "seepage_clip":
        # The TOML uses a readable sentinel value; the solver API expects the
        # concrete raster path created just above.
        modpath_params["zone_partic"] = str(seepage_clip_tif)
    result.transport.modpath.set_parameters(modpath_params)

    nper = flow_model.nper
    if isinstance(flow_model, Modflow):
        # FloPy's legacy Modflow wrapper stores dimensions under ``mf``.
        nlay, nrow, ncol = flow_model.mf.nlay, flow_model.mf.nrow, flow_model.mf.ncol
    else:
        # MODFLOW 6 wrapper exposes the dimensions directly.
        nlay, nrow, ncol = flow_model.nlay, flow_model.nrow, flow_model.ncol

    # Define runtime transport arrays once the concrete grid shape is known.
    # Values are converted from mg/L to kg/m3 for the transport solvers.
    sconc_init = np.ones((nlay, nrow, ncol)) * (100 / 1000)
    sconc_input = {
        stress_period: np.ones((nrow, ncol)) * (50 / 1000)
        for stress_period in range(1, nper)
    }
    rate_decay = np.ones((nlay, nrow, ncol)) * (1 / (2 * 365))

    runtime_parameters = dict(
        spc_name="NO3",
        sconc_init=sconc_init,
        sconc_input=sconc_input,
        rate_decay=rate_decay,
    )

    result.transport.mt3dms.set_parameters(result.cfg.transport.mt3dms.parameters.model_dump())
    result.transport.mt3dms.set_parameters(runtime_parameters)
    result.transport.modflow6gwt.set_parameters(
        result.cfg.transport.modflow6gwt.parameters.model_dump()
    )
    result.transport.modflow6gwt.set_parameters(runtime_parameters)


def on_after_transport(result: RunResult) -> None:
    """Render the final transport diagnostics after all transport solvers finish.

    This hook sees the final state of the transport process family:

    - ``result.model_modpath`` is the last executed Modpath model, if any
    - ``result.model_transport`` is the last executed concentration model, if any

    The concentration timeseries call still uses the legacy hard-coded scenario
    label ``"s1"``. That matches the default single concentration transport run
    used by this example, whose runner-generated suffix is ``_mt_s1``.
    """
    from hydromodpy.modeling import timeseries

    display_options = display_options_from_raw_toml(result.raw_toml)

    if result.model_transport is not None:
        scenario = "s1"
        timeseries.Timeseries(
            result.geographic,
            model_modflow=result.model_modflow,
            runoff=result.climatic.runoff,
            model_modpath=result.model_modpath,
            model_mt3dms=result.model_transport,
            suffix_name=scenario,
            datetime_format=True,
            subbasin_results=True,
            intermittency_weekly=False,
            intermittency_monthly=True,
            residence_times=True,
            concentration_seepage=True,
            mass_accumulated=True,
        )

    if result.model_modpath is not None:
        plot_particles_suite(result, display_options)
    if result.model_transport is not None:
        plot_transport_suite(result, display_options)
