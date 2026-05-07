"""Flow-side binders for data-to-structure updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from hydromodpy.core.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)
from hydromodpy.core.units import convert_payload_to_m, normalize_length_unit
from hydromodpy.core.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)
from hydromodpy.physics.contracts import LoadResultProto
from hydromodpy.physics.flow.sinks_sources import (
    FlowEtpConfig,
    FlowRechargeConfig,
    FlowSinksSourcesConfig,
)
from hydromodpy.physics.flow.time_forcing import (
    resolve_period_values_from_forcing,
)

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow
    from hydromodpy.physics.flow import Flow


def apply_oceanic_to_flow(
    *,
    flow: Flow,
    oceanic: LoadResultProto | None,
) -> None:
    """Inject mean sea-level value into the active ocean boundary condition."""
    if oceanic is None:
        return
    ocean_bc = flow.boundary_conditions.get("ocean")
    if ocean_bc is None:
        return
    # Priority 1: constant MSL record
    msl = [
        r
        for r in oceanic.points
        if r.variable == "mean_sea_level" and getattr(r, "is_constant", False)
    ]
    if msl:
        ocean_bc.value = msl[0].data["value"].iloc[0]
        return
    # Priority 2: mean of tide gauge time series
    sea = [r for r in oceanic.points if r.variable in ("sea_level", "oceanic")]
    if sea:
        ocean_bc.value = float(sea[0].data["value"].mean())


def apply_recharge_load_result_to_flow(
    *,
    flow: Flow,
    recharge_result: LoadResultProto | None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> bool:
    """Inject recharge from a data-manager LoadResult into flow.

    Uses the generic :func:`forcing_bridge.resolve_forcing` to handle
    spatial_mode dispatch (auto / homogeneous / heterogeneous).

    Preserves solver-side recharge policy (first_clim, negative_to_evt,
    spatial_mode, interpolation_method) from the existing flow configuration.

    Returns True if recharge was successfully injected, False otherwise.
    """
    if recharge_result is None:
        return False

    from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
    from hydromodpy.physics.forcing.forcing_bridge import resolve_forcing

    sinks_sources = getattr(flow, "sinks_sources", {})
    recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, dict) else None

    first_clim = "mean"
    spatial_mode = "auto"
    interpolation_method = "nearest"
    negative_to_evt = True
    if recharge_cfg is not None:
        first_clim = getattr(recharge_cfg, "first_clim", "mean")
        spatial_mode = getattr(recharge_cfg, "spatial_mode", "auto")
        interpolation_method = getattr(recharge_cfg, "interpolation_method", "nearest")
        negative_to_evt = bool(getattr(recharge_cfg, "negative_to_evt", True))

    # Data-manager output is always in mm/day (internal convention).
    # Flow._normalize_recharge_config has already converted recharge_cfg.units
    # to "m/s", so we cannot rely on it for the source unit here.
    unit_conversion_factor = factor_to_m_per_s("mm/day")

    resolved = resolve_forcing(
        recharge_result,
        unit_conversion_factor=unit_conversion_factor,
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
            heterogeneous_source=resolved.heterogeneous_source,
            spatial_mode=resolved.spatial_mode,
            interpolation_method=resolved.interpolation_method,
            negative_to_evt=negative_to_evt,
        )
    )
    return True


def apply_etp_load_result_to_flow(
    *,
    flow: Flow,
    etp_result: LoadResultProto | None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> bool:
    """Inject ETP from a data-manager LoadResult into flow.

    Mirrors :func:`apply_recharge_load_result_to_flow` for the ETP
    forcing. Reuses :func:`forcing_bridge.resolve_forcing` for spatial
    mode dispatch and the same ``mm/day → m/s`` conversion path.

    The runtime keeps any user-defined ETP policy (``surface_offset``,
    ``extinction_depth``, ``first_clim``, ``spatial_mode``, etc.) when
    a base ``flow.sinks_sources['etp']`` already exists; otherwise the
    typed config is created from scratch with sensible defaults that
    reproduce the legacy behaviour (``DEM - 2 m`` ET surface, 1 m
    extinction depth).

    Returns True if ETP was successfully injected, False otherwise.
    """
    if etp_result is None:
        return False

    from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
    from hydromodpy.physics.forcing.forcing_bridge import resolve_forcing

    sinks_sources = getattr(flow, "sinks_sources", {})
    etp_cfg = sinks_sources.get("etp") if isinstance(sinks_sources, dict) else None

    first_clim = "mean"
    spatial_mode = "auto"
    interpolation_method = "nearest"
    surface_offset = 2.0
    extinction_depth = 1.0
    if etp_cfg is not None:
        first_clim = getattr(etp_cfg, "first_clim", first_clim)
        spatial_mode = getattr(etp_cfg, "spatial_mode", spatial_mode)
        interpolation_method = getattr(etp_cfg, "interpolation_method", interpolation_method)
        surface_offset_q = getattr(etp_cfg, "surface_offset", None)
        if surface_offset_q is not None:
            surface_offset = float(surface_offset_q.to("m").magnitude)
        extinction_depth_q = getattr(etp_cfg, "extinction_depth", None)
        if extinction_depth_q is not None:
            extinction_depth = float(extinction_depth_q.to("m").magnitude)

    unit_conversion_factor = factor_to_m_per_s("mm/day")

    resolved = resolve_forcing(
        etp_result,
        unit_conversion_factor=unit_conversion_factor,
        simulation_window=simulation_window,
        spatial_mode=spatial_mode,
        interpolation_method=interpolation_method,
        label="etp",
    )
    if resolved is None:
        return False

    flow.set_etp(
        FlowEtpConfig(
            values=resolved.series if resolved.series is not None else 0.0,
            first_clim=first_clim,
            units="m/s",
            heterogeneous_source=resolved.heterogeneous_source,
            spatial_mode=resolved.spatial_mode,
            interpolation_method=resolved.interpolation_method,
            surface_offset=surface_offset,
            extinction_depth=extinction_depth,
        )
    )
    return True


def apply_simulation_time_to_flow_wells(
    *,
    flow: Flow,
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
    flow: Flow,
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
        boundary_kind = str(getattr(boundary_cfg, "kind", "dirichlet")).strip().lower()
        if boundary_kind == "dirichlet":
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
