"""Data step - load external forcings, bind to runtime, expose ``LoadDataStep``."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core import progress
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.progress import MILESTONE
from hydromodpy.core.time import (
    build_simulation_time_boundaries,
    resolve_simulation_time_window,
)
from hydromodpy.data.sites.gauge import check_run_gauge_area
from hydromodpy.physics.flow.structure_binders import (
    apply_cutoff_wall_to_flow,
    apply_etp_load_result_to_flow,
    apply_flow_barriers_to_flow,
    apply_lake_abacus_to_flow,
    apply_lake_bathymetry_to_flow,
    apply_lake_flux_forcings_to_flow,
    apply_lake_geometry_to_flow,
    apply_lake_meteo_forcings_to_flow,
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
    apply_runoff_to_sfr_networks,
    apply_sfr_network_to_flow,
    sfr_routes_catchment_runoff,
)
from hydromodpy.physics.hydrology.soil_reservoir.config import (
    soil_reservoir_of,
    spinup_refusal,
    steady_start_refusal,
)
from hydromodpy.simulation import ensure_flow
from hydromodpy.simulation.soil_recharge import (
    compute_soil_forcings,
    gauged_discharge_line,
    ru_ladder,
    soil_budget_lines,
)
from hydromodpy.spatial.geographic.core.derived_features import (
    attach_reference_hydrographic_network,
)
from hydromodpy.spatial.geographic.core.lake_catchments import (
    lake_areas_or_even_split,
    payload_attr,
)
from hydromodpy.spatial.geographic.core.sfr_traces import build_sfr_reach_traces
from hydromodpy.spatial.geographic.delineated_catchment import catchment_outline
from hydromodpy.spatial.geographic.structure_binders import apply_geology_to_domain
from hydromodpy.workflow.record.run_store import run_dir_of_state
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.data_description import (
    changed_sources,
    describe_loaded_data,
    description_path,
    read_data_description,
    write_data_description,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.data import DataLoadPlan

logger = get_logger(__name__)


def _log_soil_budget(lines: tuple[str, ...]) -> None:
    logger.info("\n".join(lines), extra=MILESTONE)


# ---------------------------------------------------------------------------
# Lazy-import helpers (kept at module level for patchability in tests)
# ---------------------------------------------------------------------------


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
            logger.debug(
                "[DataPlanner] %s: %s",
                type_name,
                "; ".join(reasons),
            )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def step_data_loading(ctx: WorkflowContext) -> None:
    """Load the external forcings shared by all process runs and bind them to the runtime.

    Runtime loading is delegated to ``DataManagersRuntimeLoader`` in the
    data_managers package. Structural bindings are then applied explicitly
    through domain/process binder modules.
    """
    data_plan = ctx.data_plan
    loader = _build_data_runtime_loader(
        config_path=ctx.config_path,
        data_plan=data_plan,
    )
    loader.load_all(ctx)
    check_run_gauge_area(
        getattr(ctx.cfg, "site", None),
        ctx.loaded_data.hydrometry,
        getattr(ctx.setup.geographic, "catch_area", None),
    )
    apply_structural_updates_from_data(ctx)
    ctx.loaded_data.loaded_plan_types = tuple(getattr(data_plan, "types", ()) or ())

    soil = ctx.setup.soil_forcings
    if soil is not None and not ctx.execution.lightweight:
        lines = soil_budget_lines(
            soil,
            ladder=ru_ladder(soil),
            gauged_line=gauged_discharge_line(
                ctx.loaded_data.hydrometry,
                days=soil.days,
                catchment_area_km2=getattr(ctx.setup.geographic, "catch_area", None),
            ),
            sent_to_evt="etp" in ctx.cfg.flow.active_sinks_sources,
        )
        progress.after_phase(partial(_log_soil_budget, lines))


# ---------------------------------------------------------------------------
# Structural updates from loaded data
# ---------------------------------------------------------------------------


def rebind_flow_if_stale(run_state: WorkflowContext) -> bool:
    """Rebuild ``setup.flow`` when another configuration built it, with its forcings.

    A Project builds its model phase once and drives several runs through it, so
    a sweep point, or a plain run after an overridden one, arrives with a ``flow``
    section the live flow was not built from. The new flow goes through the binder
    cascade of the data step, so it keeps every forcing (lake meteo and flux,
    runoff to SFR, ETP, oceanic) the data step gave the former one. Before the data
    are loaded there is nothing to bind: the data step does it.

    Returns True when a rebuild happened.
    """
    setup_state = run_state.setup
    flow = setup_state.flow
    if flow is None or flow.config is run_state.cfg.flow:
        return False
    setup_state.flow = None
    if run_state.loaded_data.loaded_plan_types is None:
        ensure_flow(run_state)
    else:
        apply_structural_updates_from_data(run_state)
    return True


def _resolved_window(run_state: WorkflowContext):
    resolved_grid = getattr(run_state.setup, "time_grid", None)
    if resolved_grid is not None:
        return resolved_grid.window
    return resolve_simulation_time_window(run_state.cfg)


def _bind_soil_recharge_etp(run_state: WorkflowContext, window):
    """Compute the soil forcings (when configured) and bind recharge and ETP; return the soil."""
    setup_state = run_state.setup
    data_state = run_state.loaded_data
    soil_config = soil_reservoir_of(getattr(run_state.cfg, "flow", None))
    soil = None
    if soil_config is not None:
        refusal = steady_start_refusal(run_state.cfg.flow, window)
        if refusal is not None:
            raise ConfigError(refusal)
        boundaries = build_simulation_time_boundaries(window)
        run_days = (boundaries[-1] - boundaries[0]).days
        spinup_message = spinup_refusal(soil_config, run_days)
        if spinup_message is not None:
            raise ConfigError(spinup_message)
        soil = compute_soil_forcings(
            precipitation=data_state.precipitation,
            etp=data_state.etp,
            config=soil_config,
            window=window,
            model_crs=str(setup_state.geographic.crs_proj),
            soil_capacity=getattr(data_state, "soil_capacity", None),
            catchment=catchment_outline(setup_state.geographic),
        )
    setup_state.soil_forcings = soil

    apply_recharge_load_result_to_flow(
        flow=setup_state.flow,
        recharge_result=data_state.recharge if soil is None else soil.recharge,
        simulation_window=window,
    )
    apply_etp_load_result_to_flow(
        flow=setup_state.flow,
        etp_result=getattr(data_state, "etp", None) if soil is None else soil.residual_etp,
        simulation_window=window,
        from_soil_reservoir=soil is not None,
    )
    return soil


def _bind_lakes_and_structures(run_state: WorkflowContext, window) -> None:
    """Bind the lake geometry and flux forcings, the cutoff wall and the flow barriers."""
    setup_state = run_state.setup
    data_state = run_state.loaded_data
    apply_lake_geometry_to_flow(
        flow=setup_state.flow,
        lake_geometry=getattr(data_state, "lake_geometry", None),
    )
    project_crs = getattr(getattr(setup_state, "geographic", None), "crs_proj", None)
    geo = getattr(run_state.cfg, "geographic", None)
    x_outlet = getattr(geo, "x_outlet", None)
    y_outlet = getattr(geo, "y_outlet", None)
    outlet_xy = (
        (float(x_outlet), float(y_outlet))
        if x_outlet is not None and y_outlet is not None
        else None
    )
    apply_cutoff_wall_to_flow(
        flow=setup_state.flow,
        project_crs=project_crs,
        outlet_xy=outlet_xy,
        data_dir=getattr(getattr(run_state.cfg, "workspace", None), "data_dir", None),
    )
    apply_flow_barriers_to_flow(flow=setup_state.flow, project_crs=project_crs)
    apply_lake_abacus_to_flow(
        flow=setup_state.flow,
        lake_abacus=getattr(data_state, "lake_abacus", None),
    )
    apply_lake_bathymetry_to_flow(
        flow=setup_state.flow,
        lake_bathymetry=getattr(data_state, "lake_bathymetry", None),
    )
    apply_lake_flux_forcings_to_flow(
        flow=setup_state.flow,
        lake_inflow=getattr(data_state, "lake_inflow", None),
        lake_withdrawal=getattr(data_state, "lake_withdrawal", None),
        simulation_window=window,
    )


def _bind_runoff_and_sfr(run_state: WorkflowContext, window, soil) -> None:
    """Route the catchment runoff to the SFR networks and lakes, then bind the SFR traces."""
    setup_state = run_state.setup
    data_state = run_state.loaded_data
    catch_area_km2 = getattr(getattr(setup_state, "geographic", None), "catch_area", None)
    catch_area_m2 = float(catch_area_km2) * 1.0e6 if catch_area_km2 else None
    runoff = getattr(data_state, "runoff", None) if soil is None else soil.runoff
    # Routed-first precedence: an active SFR network takes the catchment runoff
    # (the lake meteo binder then skips its direct runoff feed; the water reaches
    # a coupled lake through MVR instead).
    apply_runoff_to_sfr_networks(
        flow=setup_state.flow,
        runoff=runoff,
        simulation_window=window,
        catchment_area_m2=catch_area_m2,
    )
    apply_lake_meteo_forcings_to_flow(
        flow=setup_state.flow,
        precipitation=getattr(data_state, "precipitation", None),
        etp=getattr(data_state, "etp", None),
        runoff=runoff,
        simulation_window=window,
        catchment_area_m2=catch_area_m2,
        lake_contributing_areas_m2=(lake_runoff_areas(setup_state) if runoff is not None else None),
    )
    if setup_state.geographic_features is not None:
        setup_state.geographic_features = attach_reference_hydrographic_network(
            setup_state.geographic_features,
            data_state.hydrography,
        )
    bind_sfr_network_traces(run_state)


def apply_structural_updates_from_data(
    run_state: WorkflowContext,
) -> None:
    """Bind loaded data objects to runtime structures using explicit updaters."""
    setup_state = run_state.setup
    data_state = run_state.loaded_data
    apply_geology_to_domain(domain=setup_state.domain, geology=data_state.geology)
    ensure_flow(run_state)
    apply_oceanic_to_flow(flow=setup_state.flow, oceanic=data_state.oceanic)
    window = _resolved_window(run_state)
    soil = _bind_soil_recharge_etp(run_state, window)
    _bind_lakes_and_structures(run_state, window)
    _bind_runoff_and_sfr(run_state, window, soil)


# ---------------------------------------------------------------------------
# Lake runoff shares and SFR reach-network binding
# ---------------------------------------------------------------------------


def lake_runoff_areas(setup_state: object) -> dict[str, float] | None:
    """Return the area each lake drains, or None when the basin is shared evenly.

    Only the lakes fed directly need it: an active SFR network routes the runoff
    and a lone lake takes the whole basin. The areas are read on the D8 grid of
    the regional flow products, the only drainage that exists before the mesh.
    None hands the choice back to the binder, which splits the basin evenly.
    """
    flow = getattr(setup_state, "flow", None)
    if flow is None or sfr_routes_catchment_runoff(flow):
        return None
    lakes = getattr(flow, "sinks_sources", {}).get("lakes") or {}
    if len(lakes) < 2:
        return None
    geographic = getattr(setup_state, "geographic", None)
    flow_products = getattr(geographic, "_flow_products", None)
    return lake_areas_or_even_split(
        lakes,
        d8_pointer_tif=str(flow_products.direc) if flow_products is not None else None,
        watershed_shp=getattr(geographic, "watershed_shp", None),
    )


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
        if payload_attr(payload, "reaches") is None
    }


def bind_sfr_network_traces(run_state: WorkflowContext) -> None:
    """Delineate (once) and bind the SFR reach traces onto the runtime flow.

    The traces are cached on ``setup`` so the per-run Flow rebuilds re-bind
    without recomputing.
    """
    setup_state = run_state.setup
    flow = setup_state.flow
    if flow is None:
        return
    networks = _sfr_networks_needing_trace(flow)
    if not networks:
        return
    if setup_state.sfr_reach_traces is None:
        setup_state.sfr_reach_traces = build_sfr_reach_traces(
            setup_state.geographic,
            networks,
            getattr(flow, "sinks_sources", {}).get("lakes") or {},
        )
    apply_sfr_network_to_flow(flow=flow, reach_traces=setup_state.sfr_reach_traces)


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class LoadDataStep:
    """Ingest external + custom data via data managers."""

    name = "load_data"
    reads: ClassVar[tuple[str, ...]] = ("ctx", "run_dir")
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = ("data",)

    def depends_on(self) -> tuple[str, ...]:
        return ("build_geographic",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("LoadDataStep requires 'ctx' in state.data")

        step_data_loading(ctx)
        self._describe(ctx, state)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def artifacts(self, state_out: PipelineState) -> tuple[str, ...]:
        """Return the document naming what this load bound to the runtime.

        The forcing files themselves are not declared: they are what the step
        read, not what it produced. What it produced is the binding, and the
        document holds it - so a resume that finds the document gone, or
        truncated, refuses instead of carrying on over an undescribed load.
        """
        run_dir = run_dir_of_state(state_out)
        if run_dir is None:
            return ()
        path = description_path(run_dir)
        return (str(path),) if path.is_file() else ()

    def _describe(self, ctx: WorkflowContext, state: PipelineState) -> dict | None:
        """Write what this load read, beside the resume checkpoint of the run."""
        run_dir = run_dir_of_state(state)
        if run_dir is None:
            return None
        payload = describe_loaded_data(
            ctx.loaded_data,
            plan_types=tuple(getattr(ctx.data_plan, "types", ()) or ()),
        )
        write_data_description(run_dir, state.run_id, payload)
        return payload

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Re-run load_data, and say so when the sources moved underneath.

        Replaying is honest here: the data managers consult their local caches,
        so the step reads back what it read the first time rather than
        recomputing anything. What replaying cannot guarantee is that the files
        are the same files - a forcing rewritten between the crash and the
        restart is loaded silently, and the resumed run then carries a mesh
        from before and a forcing from after. The description the first load
        left says which sources it used, so the divergence is at least named.
        """
        run_dir = run_dir_of_state(prior_state)
        before = read_data_description(run_dir) if run_dir is not None else None
        state = self.run(prior_state)
        if before is not None and run_dir is not None:
            after = read_data_description(run_dir)
            for variable in changed_sources(before, after):
                logger.warning(
                    "load_data.source_changed_since_the_run_started variable=%s run=%s",
                    variable,
                    run_id,
                )
        return state

    def is_prebuilt(self, state: PipelineState) -> bool:
        """True when the in-memory ctx already covers the current data plan."""
        ctx = state.get("ctx")
        if ctx is None:
            return False
        loaded = getattr(ctx.loaded_data, "loaded_plan_types", None)
        if loaded is None:
            return False
        return set(getattr(ctx.data_plan, "types", ()) or ()) <= set(loaded)
