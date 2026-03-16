"""Flow-side binders for data-to-structure updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.process.flow.sinks_sources import FlowSinksSourcesConfig
from hydromodpy.process.flow.time_forcing import (
    resolve_period_values_from_forcing,
)
from hydromodpy.support.units import convert_payload_to_m, normalize_length_unit
from hydromodpy.support.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)
from hydromodpy.simulation.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)

if TYPE_CHECKING:
    from hydromodpy.data_managers.contracts.load_result import LoadResult
    from hydromodpy.process import Flow
    from hydromodpy.simulation.time import ResolvedSimulationTimeWindow


def apply_oceanic_to_flow(
    *,
    flow: "Flow",
    oceanic: "LoadResult | None",
) -> None:
    """Inject mean sea-level value into the active ocean boundary condition."""
    if oceanic is None:
        return
    ocean_bc = flow.boundary_conditions.get("ocean")
    if ocean_bc is None:
        return
    # Priority 1: constant MSL record
    msl = [r for r in oceanic.points if r.variable == "mean_sea_level" and getattr(r, "is_constant", False)]
    if msl:
        ocean_bc.value = msl[0].data["value"].iloc[0]
        return
    # Priority 2: mean of tide gauge time series
    sea = [r for r in oceanic.points if r.variable in ("sea_level", "oceanic")]
    if sea:
        ocean_bc.value = float(sea[0].data["value"].mean())


def apply_recharge_load_result_to_flow(
    *,
    flow: "Flow",
    recharge_result: "LoadResult | None",
    simulation_window: "ResolvedSimulationTimeWindow | None" = None,
) -> bool:
    """Inject recharge from a data-manager LoadResult into flow.

    Uses the generic :func:`forcing_bridge.resolve_forcing` to handle
    spatial_mode dispatch (auto / homogeneous / heterogeneous).

    Preserves solver-side recharge policy (first_clim, negative_to_evt)
    from the existing flow configuration.

    Returns True if recharge was successfully injected, False otherwise.
    """
    if recharge_result is None:
        return False

    from hydromodpy.forcing.forcing_bridge import resolve_forcing
    from hydromodpy.forcing.forcing_bridge import _MM_PER_DAY_TO_M_PER_S

    sinks_sources = getattr(flow, "sinks_sources", {})
    recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, dict) else None

    first_clim = "mean"
    negative_to_evt = True
    spatial_mode = "auto"
    interpolation_method = "nearest"
    if recharge_cfg is not None:
        first_clim = getattr(recharge_cfg, "first_clim", "mean")
        negative_to_evt = getattr(recharge_cfg, "negative_to_evt", True)
        spatial_mode = getattr(recharge_cfg, "spatial_mode", "auto")
        interpolation_method = getattr(recharge_cfg, "interpolation_method", "nearest")

    resolved = resolve_forcing(
        recharge_result,
        unit_conversion_factor=_MM_PER_DAY_TO_M_PER_S,
        simulation_window=simulation_window,
        spatial_mode=spatial_mode,
        interpolation_method=interpolation_method,
        label="recharge",
    )
    if resolved is None:
        return False

    flow.set_recharge(
        FlowRechargeConfig(
            values=resolved.series if resolved.series is not None else 0.0,
            first_clim=first_clim,
            units="m/s",
            negative_to_evt=negative_to_evt,
            heterogeneous_source=resolved.heterogeneous_source,
            spatial_mode=resolved.spatial_mode,
            interpolation_method=resolved.interpolation_method,
        )
    )
    return True


def apply_simulation_time_to_flow_wells(
    *,
    flow: "Flow",
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> None:
    """Resolve flow well.forcing payloads to period-aligned well.flux values."""
    if simulation_window is None:
        return

    sinks_sources = getattr(flow, "sinks_sources", {})
    wells = sinks_sources.get("wells", {}) if isinstance(sinks_sources, Mapping) else {}
    if not wells:
        return

    updated_wells: dict[str, object] = {}
    changed = False
    for well_id, well_cfg in wells.items():
        forcing = getattr(well_cfg, "forcing", None)
        if forcing is None:
            updated_wells[well_id] = well_cfg
            continue

        label = f"flow.sinks_sources.wells.{well_id}.forcing"
        resolved_flux = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=simulation_window,
            nper=len(build_simulation_time_boundaries(simulation_window)) - 1,
            label=label,
        )
        source_units = normalize_m3_per_s_unit(
            str(getattr(forcing, "units", None) or getattr(well_cfg, "units", "m3/s"))
        )
        flux_si = [
            convert_to_m3_per_s(
                value,
                unit=source_units,
                label=f"{label}[{idx}]",
            )
            for idx, value in enumerate(resolved_flux)
        ]

        updated_wells[well_id] = well_cfg.model_copy(
            update={"flux": flux_si, "forcing": None, "units": "m3/s"}
        )
        changed = True

    if not changed:
        return

    flow.set_sinks_sources(
        FlowSinksSourcesConfig(
            wells=updated_wells,
            recharge=sinks_sources.get("recharge") if isinstance(sinks_sources, Mapping) else None,
        )
    )


def apply_simulation_time_to_flow_boundary_conditions(
    *,
    flow: "Flow",
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> None:
    """Resolve flow.bc.*.forcing payloads to period-aligned boundary.value series."""
    if simulation_window is None:
        return

    boundary_conditions = getattr(flow, "boundary_conditions", {})
    if not isinstance(boundary_conditions, Mapping) or not boundary_conditions:
        return

    updated_boundaries: dict[str, object] = {}
    changed = False
    for bc_id, boundary_cfg in boundary_conditions.items():
        forcing = getattr(boundary_cfg, "forcing", None)
        if forcing is None:
            updated_boundaries[bc_id] = boundary_cfg
            continue

        label = f"flow.bc.{bc_id}.forcing"
        resolved_values = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=simulation_window,
            nper=len(build_simulation_time_boundaries(simulation_window)) - 1,
            label=label,
        )
        updated_units = getattr(boundary_cfg, "units", "m")
        boundary_type = str(getattr(boundary_cfg, "type", "dirichlet")).strip().lower()
        if boundary_type == "dirichlet":
            source_units = normalize_length_unit(
                str(getattr(forcing, "units", None) or updated_units or "m")
            )
            resolved_values = convert_payload_to_m(
                resolved_values,
                unit=source_units,
                label=f"{label}.values",
            )
            updated_units = "m"

        updated_boundaries[bc_id] = boundary_cfg.model_copy(
            update={"value": resolved_values, "forcing": None, "units": updated_units}
        )
        changed = True

    if not changed:
        return

    flow.set_boundary_conditions(
        boundary_conditions=updated_boundaries,
        application_domains=getattr(flow, "boundary_condition_application_domains", None),
    )
