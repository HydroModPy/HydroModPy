"""Data step - load external forcings, bind to runtime, expose ``LoadDataStep``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time import resolve_simulation_time_window
from hydromodpy.physics.flow.structure_binders import (
    apply_etp_load_result_to_flow,
    apply_lake_abacus_to_flow,
    apply_lake_flux_forcings_to_flow,
    apply_lake_geometry_to_flow,
    apply_lake_meteo_forcings_to_flow,
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
    apply_runoff_to_sfr_networks,
    apply_sfr_network_to_flow,
)
from hydromodpy.simulation import ensure_flow
from hydromodpy.spatial.geographic.core.derived_features import (
    attach_reference_hydrographic_network,
)
from hydromodpy.spatial.geographic.structure_binders import apply_geology_to_domain
from hydromodpy.workflow.internals.state import GeographicState, LoadedState, PipelineState

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.data import DataLoadPlan

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lazy-import helpers (kept at module level for patchability in tests)
# ---------------------------------------------------------------------------


def _build_data_plan(*args, **kwargs):
    """Import planner lazily to keep launcher imports lightweight in tests."""
    from hydromodpy.data import DataPlanner

    return DataPlanner().build(*args, **kwargs)


def _build_data_runtime_loader(*args, **kwargs):
    """Import runtime loader lazily to avoid importing the full data stack at module import."""
    from hydromodpy.data import DataManagersRuntimeLoader

    return DataManagersRuntimeLoader(*args, **kwargs)


# ---------------------------------------------------------------------------
# Data plan logging
# ---------------------------------------------------------------------------


def log_data_plan(data_plan: DataLoadPlan) -> None:
    """Log concise planner diagnostics when inferred types are present."""
    if not data_plan.inferred_types:
        return
    logger.info(
        "[DataPlanner] inferred data types: %s",
        ", ".join(data_plan.inferred_types),
    )
    for type_name in data_plan.inferred_types:
        reasons = data_plan.reasons_for(type_name)
        if reasons:
            logger.info(
                "[DataPlanner] %s: %s",
                type_name,
                "; ".join(reasons),
            )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def run_data(
    config_path: str | Path,
    data_plan: DataLoadPlan,
    run_state: WorkflowContext,
) -> None:
    """Load the external forcings shared by all process runs.

    Runtime loading is delegated to ``DataManagersRuntimeLoader`` in the
    data_managers package. Structural bindings are then applied explicitly
    through domain/process binder modules.
    """
    loader = _build_data_runtime_loader(
        config_path=config_path,
        data_plan=data_plan,
    )
    loader.load_all(run_state)
    apply_structural_updates_from_data(run_state)
    run_state.loaded_data.loaded_plan_types = tuple(getattr(data_plan, "types", ()) or ())


# ---------------------------------------------------------------------------
# Structural updates from loaded data
# ---------------------------------------------------------------------------


def apply_structural_updates_from_data(
    run_state: WorkflowContext,
) -> None:
    """Bind loaded data objects to runtime structures using explicit updaters."""
    setup_state = run_state.setup
    data_state = run_state.loaded_data
    apply_geology_to_domain(domain=setup_state.domain, geology=data_state.geology)
    ensure_flow(run_state)
    apply_oceanic_to_flow(flow=setup_state.flow, oceanic=data_state.oceanic)

    resolved_grid = getattr(setup_state, "time_grid", None)
    window = (
        resolved_grid.window
        if resolved_grid is not None
        else resolve_simulation_time_window(run_state.cfg)
    )
    apply_recharge_load_result_to_flow(
        flow=setup_state.flow,
        recharge_result=data_state.recharge,
        simulation_window=window,
    )
    apply_etp_load_result_to_flow(
        flow=setup_state.flow,
        etp_result=getattr(data_state, "etp", None),
        simulation_window=window,
    )
    apply_lake_geometry_to_flow(
        flow=setup_state.flow,
        lake_geometry=getattr(data_state, "lake_geometry", None),
    )
    apply_lake_abacus_to_flow(
        flow=setup_state.flow,
        lake_abacus=getattr(data_state, "lake_abacus", None),
    )
    apply_lake_flux_forcings_to_flow(
        flow=setup_state.flow,
        lake_inflow=getattr(data_state, "lake_inflow", None),
        lake_withdrawal=getattr(data_state, "lake_withdrawal", None),
        simulation_window=window,
    )
    _catch_area_km2 = getattr(getattr(setup_state, "geographic", None), "catch_area", None)
    _catch_area_m2 = float(_catch_area_km2) * 1.0e6 if _catch_area_km2 else None
    # Routed-first precedence: an active SFR network takes the catchment runoff
    # (the lake meteo binder then skips its direct runoff feed; the water reaches
    # a coupled lake through MVR instead).
    apply_runoff_to_sfr_networks(
        flow=setup_state.flow,
        runoff=getattr(data_state, "runoff", None),
        simulation_window=window,
        catchment_area_m2=_catch_area_m2,
    )
    apply_lake_meteo_forcings_to_flow(
        flow=setup_state.flow,
        precipitation=getattr(data_state, "precipitation", None),
        etp=getattr(data_state, "etp", None),
        runoff=getattr(data_state, "runoff", None),
        simulation_window=window,
        catchment_area_m2=_catch_area_m2,
    )
    if setup_state.geographic_features is not None:
        setup_state.geographic_features = attach_reference_hydrographic_network(
            setup_state.geographic_features,
            data_state.hydrography,
        )
    bind_sfr_network_traces(run_state)


# ---------------------------------------------------------------------------
# SFR reach-network delineation binding
# ---------------------------------------------------------------------------


def _payload_attr(payload: object, name: str) -> object:
    if isinstance(payload, dict):
        return payload.get(name)
    return getattr(payload, name, None)


def _length_to_m(value: object) -> float:
    to = getattr(value, "to", None)
    if callable(to):
        return float(to("m").magnitude)
    return float(getattr(value, "magnitude", value))  # type: ignore[arg-type]


def _read_watershed_polygons(geographic: object) -> list[object]:
    """Read the delineated watershed polygon(s) used to scope the stream links.

    The full-grid link raster covers the whole regional DEM; only the links
    inside the modelled catchment can map onto the solver mesh.
    """
    watershed_shp = getattr(geographic, "watershed_shp", None)
    if not watershed_shp or not Path(str(watershed_shp)).exists():
        return []
    import geopandas as gpd

    gdf = gpd.read_file(str(watershed_shp))
    return [geometry for geometry in gdf.geometry if geometry is not None]


def _sfr_networks_needing_trace(flow: object) -> dict[str, object]:
    """Return the active SFR network payloads that need a delineated trace."""
    active_bc = {str(name).lower() for name in getattr(flow, "active_bc", []) or []}
    if "sfr" not in active_bc:
        return {}
    sinks_sources = getattr(flow, "sinks_sources", {})
    sfr = sinks_sources.get("sfr") if isinstance(sinks_sources, dict) else None
    if not sfr:
        return {}
    return {
        str(network_id): payload
        for network_id, payload in sfr.items()
        if _payload_attr(payload, "reaches") is None
    }


def _check_sfr_threshold_consistency(
    *,
    network_id: str,
    payload: object,
    products_threshold_cells: float | None,
    dem_res_m: float,
) -> None:
    """The SFR network is derived from the geographic.river_network link raster,
    so the SFR stream threshold must resolve to the same cell count."""
    if products_threshold_cells is None:
        return
    cells = _payload_attr(payload, "stream_threshold_cells")
    km2 = _payload_attr(payload, "stream_threshold_km2")
    if cells is not None:
        requested = float(cells)
    elif km2 is not None:
        requested = float(km2) * 1.0e6 / (float(dem_res_m) ** 2)
    else:
        return
    reference = float(products_threshold_cells)
    if abs(requested - reference) > max(1.0, 1e-6 * reference):
        raise ConfigError(
            f"flow.sinks_sources.sfr.{network_id} stream threshold resolves to "
            f"{requested:.0f} cells but geographic.river_network produced the link "
            f"raster at {reference:.0f} cells. The v1 SFR network reuses that raster: "
            "align the two thresholds (or drop the SFR one in favour of "
            "stream_threshold_cells = the geographic value)."
        )


def bind_sfr_network_traces(run_state: WorkflowContext) -> None:
    """Delineate (once) and bind the SFR reach traces onto the runtime flow.

    Reads the FULL DEM-grid rasters from the river-network products (the clipped
    rasters have a different extent), rasterizes the bound lake polygons so the
    terminal reach is flagged, and attaches one ``SfrReachTrace`` per network
    through the physics binder. The traces are cached on ``setup`` so the
    per-run Flow rebuilds re-bind without recomputing.
    """
    setup_state = run_state.setup
    flow = setup_state.flow
    if flow is None:
        return
    networks = _sfr_networks_needing_trace(flow)
    if not networks:
        return

    if setup_state.sfr_reach_traces is None:
        from hydromodpy.spatial.geographic.core.sfr_network import (
            build_sfr_reach_trace_from_products,
        )

        geographic = setup_state.geographic
        products = getattr(geographic, "_river_network_products", None)
        if products is None or not bool(getattr(products, "enabled", False)):
            raise ConfigError(
                "flow.sinks_sources.sfr needs the river-network products; set "
                "[geographic.river_network] enabled = true."
            )
        link_full = getattr(products, "stream_link_id_full_tif", None)
        if link_full is None:
            raise ConfigError(
                "flow.sinks_sources.sfr needs the stream-link raster; set "
                "[geographic.river_network] compute_stream_links = true."
            )
        flow_products = getattr(geographic, "_flow_products", None)
        if flow_products is None:
            raise ConfigError(
                "flow.sinks_sources.sfr needs the regional flow products (corrected "
                "DEM + D8 pointer); run the geographic preprocessing first."
            )
        dem_res_m = float(geographic.dem_res)
        lakes = getattr(flow, "sinks_sources", {}).get("lakes") or {}
        lake_polygons = [
            _payload_attr(payload, "polygon")
            for payload in lakes.values()
            if _payload_attr(payload, "polygon") is not None
        ]
        watershed_polygons = _read_watershed_polygons(geographic)

        traces: dict[str, object] = {}
        for network_id, payload in networks.items():
            _check_sfr_threshold_consistency(
                network_id=network_id,
                payload=payload,
                products_threshold_cells=getattr(products, "threshold_cells", None),
                dem_res_m=dem_res_m,
            )
            min_slope = _payload_attr(payload, "min_slope")
            min_reach_length = _payload_attr(payload, "min_reach_length")
            traces[network_id] = build_sfr_reach_trace_from_products(
                stream_link_id_full_tif=str(link_full),
                d8_pointer_tif=str(flow_products.direc),
                flow_acc_cells_tif=str(products.flow_acc_cells_tif),
                dem_correc_tif=str(flow_products.correc),
                dem_res_m=dem_res_m,
                stream_order_strahler_full_tif=getattr(
                    products, "stream_order_strahler_full_tif", None
                ),
                lake_polygons=lake_polygons,
                watershed_polygons=watershed_polygons,
                min_slope=float(min_slope) if min_slope is not None else 1e-4,
                min_reach_length_m=(
                    _length_to_m(min_reach_length) if min_reach_length is not None else 0.0
                ),
            )
        setup_state.sfr_reach_traces = traces

    apply_sfr_network_to_flow(flow=flow, reach_traces=setup_state.sfr_reach_traces)


# ---------------------------------------------------------------------------
# Step entry point (unified signature for workflow pipelines)
# ---------------------------------------------------------------------------


def step_data_loading(ctx: WorkflowContext) -> None:
    """Load forcings into ``ctx.loaded_data`` and bind them to runtime structures."""
    run_data(
        config_path=ctx.config_path,
        data_plan=ctx.data_plan,
        run_state=ctx,
    )


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class LoadDataStep:
    """Ingest external + custom data via data managers."""

    name = "load_data"
    tin: ClassVar[type] = GeographicState
    tout: ClassVar[type] = LoadedState
    config_sections: ClassVar[tuple[str, ...]] = ("data",)

    def depends_on(self) -> tuple[str, ...]:
        return ("build_geographic",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("LoadDataStep requires 'ctx' in state.data")

        step_data_loading(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Re-run load_data: data managers consult their local caches."""
        return self.run(prior_state)

    def is_prebuilt(self, state: PipelineState) -> bool:
        """True when the in-memory ctx already covers the current data plan."""
        ctx = state.get("ctx")
        if ctx is None:
            return False
        loaded = getattr(ctx.loaded_data, "loaded_plan_types", None)
        if loaded is None:
            return False
        return set(getattr(ctx.data_plan, "types", ()) or ()) <= set(loaded)
