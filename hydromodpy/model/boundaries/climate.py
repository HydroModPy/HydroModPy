"""Sea level, recharge and ETP put on a Flow, from loaded forcings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.model.boundaries.boundary_condition_registry import (
    boundary_conditions_mapping_from_flow,
)
from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.cells import spatial_mean_from_fields
from hydromodpy.model.forcing.validation import refuse_an_impossible_recharge
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig, recharge_factor_of

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow
    from hydromodpy.model.flow import Flow

logger = get_logger(__name__)


def apply_oceanic_to_flow(
    *,
    flow: Flow,
    oceanic: LoadResultProto | None,
) -> None:
    """Inject mean sea-level value into the active ocean boundary condition."""
    if oceanic is None:
        return
    ocean_bc = boundary_conditions_mapping_from_flow(flow).get("ocean")
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


def _peak_mm_day_of_a_recharge_source(source: LoadResultProto) -> float:
    """Return the largest rate of a recharge source, a grid through its spatial mean, in mm/day."""
    peaks = [float(record.data["value"].abs().max()) for record in source.points]
    if source.has_fields:
        spatial_mean = spatial_mean_from_fields(source)
        if spatial_mean is not None:
            peaks.append(float(spatial_mean.abs().max()))
    return max(peaks, default=0.0)


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

    from hydromodpy.core.units.quantities import factor_to_m_per_s
    from hydromodpy.model.forcing.forcing_bridge import resolve_forcing, scaled_load_result

    if "recharge" not in (getattr(flow, "active_sinks_sources", None) or []):
        logger.warning(
            "[data.recharge] is loaded and [flow.sinks_sources.recharge] is absent or says "
            "enabled = false, so the model receives no recharge: declare the table, or "
            "remove it from data.types."
        )

    # Read from the declared section: the payload of the flow already applied its factor.
    factor = recharge_factor_of(getattr(flow, "config", None))
    recharge_result = scaled_load_result(recharge_result, factor)
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
    refuse_an_impossible_recharge(
        _peak_mm_day_of_a_recharge_source(recharge_result), label="[data.recharge]"
    )

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
    from_soil_reservoir: bool = False,
) -> bool:
    """Inject ETP from a data-manager LoadResult into flow.

    Mirrors :func:`apply_recharge_load_result_to_flow` for the ETP
    forcing. Reuses :func:`forcing_bridge.resolve_forcing` for spatial
    mode dispatch and the same ``mm/day → m/s`` conversion path.

    The runtime keeps any user-defined ETP policy (``surface_offset``,
    ``extinction_depth``, ``first_clim``, ``spatial_mode``, etc.) when
    a base ``flow.sinks_sources['etp']`` already exists; otherwise the
    typed config is created from scratch with the defaults of the table
    (``DEM - 2 m`` ET surface, 2 m extinction depth).
    ``from_soil_reservoir=True`` is what the soil
    binder passes: the EVT surface defaults to 0 m below the drain
    elevation instead of 2 m below the topographic surface, unless the
    file wrote ``surface_offset`` itself, and the returned config is
    marked so MODFLOW 6 knows this ETP is what the soil left unmet.

    Returns True if ETP was successfully injected, False otherwise.
    """
    if etp_result is None:
        return False

    from hydromodpy.core.units.quantities import factor_to_m_per_s
    from hydromodpy.model.forcing.forcing_bridge import resolve_forcing

    sinks_sources = getattr(flow, "sinks_sources", {})
    etp_cfg = sinks_sources.get("etp") if isinstance(sinks_sources, dict) else None

    first_clim = "mean"
    spatial_mode = "auto"
    interpolation_method = "nearest"
    surface_offset = 0.0 if from_soil_reservoir else 2.0
    extinction_depth = 2.0
    if etp_cfg is not None:
        first_clim = getattr(etp_cfg, "first_clim", first_clim)
        spatial_mode = getattr(etp_cfg, "spatial_mode", spatial_mode)
        interpolation_method = getattr(etp_cfg, "interpolation_method", interpolation_method)
        surface_offset_q = getattr(etp_cfg, "surface_offset", None)
        fields_set = getattr(etp_cfg, "model_fields_set", set())
        if surface_offset_q is not None and (
            not from_soil_reservoir or "surface_offset" in fields_set
        ):
            surface_offset = float(surface_offset_q.to("m").magnitude)
        extinction_depth_q = getattr(etp_cfg, "extinction_depth", None)
        if extinction_depth_q is not None:
            extinction_depth = float(extinction_depth_q)

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

    etp_config = FlowEtpConfig(
        values=resolved.series if resolved.series is not None else 0.0,
        first_clim=first_clim,
        units="m/s",
        heterogeneous_source=resolved.heterogeneous_source,
        spatial_mode=resolved.spatial_mode,
        interpolation_method=resolved.interpolation_method,
        surface_offset=surface_offset,
        extinction_depth=extinction_depth,
    )
    if from_soil_reservoir:
        etp_config._from_soil_reservoir = True
    flow.set_etp(etp_config)
    return True


def watershed_mean_rates(
    result: LoadResultProto | None,
    label: str,
    simulation_window: ResolvedSimulationTimeWindow,
) -> list[float] | None:
    """Reduce one catchment data family to per-period watershed-mean rates [m/s]."""
    if result is None:
        return None
    from hydromodpy.core.units.quantities import factor_to_m_per_s
    from hydromodpy.model.forcing.forcing_bridge import resolve_forcing

    resolved = resolve_forcing(
        result,
        unit_conversion_factor=factor_to_m_per_s("mm/day"),
        simulation_window=simulation_window,
        spatial_mode="homogeneous",
        label=label,
    )
    if resolved is None or resolved.series is None:
        return None
    return [float(v) for v in resolved.series]
