# -*- coding: utf-8 -*-
"""Study-specific hooks for ``examples/example12launcher``.

The launcher discovers this file next to ``config.toml`` and imports any
function named ``on_before_<phase>`` or ``on_after_<phase>``. Each hook
receives the shared :class:`launchers.LauncherRunState` instance and mutates it
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
- ``on_before_transport`` is now a compatibility hook kept as a no-op. Runtime
  flow-to-transport preprocessing moved to transport solver adapters.

This file intentionally does not recreate the generic launcher boilerplate
(workspace, geographic context, domain, solver instances, etc.). Those objects
already exist on ``LauncherRunState`` when the relevant hook is called.

Postprocess actions that were previously in ``on_after_flow`` and
``on_after_transport`` are now driven by the `[postprocess]` TOML section.
"""

from __future__ import annotations

import pandas as pd

from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig
from launchers import LauncherRunState


def on_after_data(result: LauncherRunState) -> None:
    """Seed climate forcing once generic data-manager loading is complete.

    This hook extends the generic launcher ``data`` phase. At this point the
    launcher has already created:

    - ``result.data.climatic``
    - ``result.data.hydrography``
    - ``result.data.intermittency``
    - ``result.data.hydrometry``

    Those datasets now come from ``[data.*]`` TOML sections via the generic
    runtime loader. This hook keeps only the study-specific climate bootstrap.
    """
    data_path = result.cfg.workspace.data_path

    # Seed the climatic object with one transient year of observed recharge and
    # runoff. Later hooks overwrite the actual synthetic forcing used by the
    # flow model, but they still rely on these series as the initial template.
    result.data.climatic.update_recharge_reanalysis(
        path_file=data_path / "_climate_REANALYSIS.csv",
        clim_mod="REA",
        clim_sce="historic",
        first_year=2003,
        last_year=2003,
        time_step="ME",
        sim_state="transient",
    )
    result.data.climatic.update_runoff_reanalysis(
        path_file=data_path / "_climate_REANALYSIS.csv",
        clim_mod="REA",
        clim_sce="historic",
        first_year=2003,
        last_year=2003,
        time_step="ME",
        sim_state="transient",
    )


def on_before_flow(result: LauncherRunState) -> None:
    """Prepare the shared flow inputs used by the whole flow process family.

    This hook runs once before the first flow solver in the current process
    block. If several flow solvers are declared, they all consume the same
    ``result.setup.flow`` object configured here.

    The hook performs four tasks:

    - replace the raw reanalysis recharge by a synthetic monthly scenario
    - derive runoff from recharge
    - set study-specific model naming and preprocessing options
    - inject the final recharge policy into ``result.setup.flow``

    The synthetic scenario is intentionally simple:

    - January, February, November, December: ``2 mm/day``
    - March, April, May, June, August, September, October: ``0 mm/day``
    - July: ``-1 mm/day`` so that evapotranspiration handling is exercised
    """
    raw_recharge = result.data.climatic.recharge

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

    result.data.climatic.update_recharge(recharge, sim_state=result.setup.flow.flow_regime)
    result.data.climatic.update_runoff(runoff, sim_state=result.setup.flow.flow_regime)

    alpha = 15
    hydraulic_conductivity = 5e-5 * 24 * 3600
    specific_yield = 2 / 100

    model_version = "TRANS1"
    model_name = (
        f"{model_version}_K{hydraulic_conductivity / 24 / 3600:.1e}"
        f"_a{alpha:.1f}_Sy{specific_yield * 100:.1f}"
    )
    result.setup.settings.update_model_name(model_name)
    result.setup.settings.update_box_model(box=True)
    result.setup.settings.update_sink_fill(sink_fill=False)
    result.setup.settings.update_check_model(
        plot_cross=True,
        check_grid=True,
        cross_ylim=[0, 200],
    )

    # Reuse the policy declared in TOML for stress period 0 and negative
    # recharge handling. The time series values themselves are the synthetic
    # series computed above.
    recharge_config = result.setup.flow.sinks_sources.get("recharge")
    first_clim = recharge_config.first_clim if recharge_config is not None else "mean"
    result.data.climatic.update_first_clim(first_clim)

    negative_to_evt = recharge_config.negative_to_evt if recharge_config is not None else True
    result.setup.flow.set_recharge(
        FlowRechargeConfig(
            values=result.data.climatic.recharge,
            first_clim=result.data.climatic.first_clim,
            negative_to_evt=negative_to_evt,
        )
    )


def on_before_transport(result: LauncherRunState) -> None:
    """Compatibility no-op.

    Transport runtime preprocessing is now handled in transport adapters:

    - concentration payload expansion from flow grid (mt3dms/modflow6gwt),
    - seepage raster clipping for ``zone_partic='seepage_clip'`` (modpath).
    """
    _ = result
