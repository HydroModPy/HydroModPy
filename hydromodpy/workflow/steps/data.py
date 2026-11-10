"""Data step - load external forcings, bind to runtime, expose ``LoadDataStep``."""

from __future__ import annotations

import hashlib
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.catchment.algorithms.derived_features import attach_reference_hydrographic_network
from hydromodpy.catchment.algorithms.lake_catchments import lake_areas_or_even_split, payload_attr
from hydromodpy.catchment.algorithms.sfr_traces import build_sfr_reach_traces
from hydromodpy.catchment.preprocess.delineated_catchment import catchment_outline
from hydromodpy.core.console import progress
from hydromodpy.core.console.progress import MILESTONE
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.time import (
    build_simulation_time_boundaries,
    resolve_simulation_time_window,
)
from hydromodpy.data.sites.gauge import check_run_gauge_area
from hydromodpy.data.variables.lake_abacus.read import lake_abacus
from hydromodpy.data.variables.lake_bathymetry.read import lake_bathymetry
from hydromodpy.data.variables.lake_geometry.read import lake_polygons
from hydromodpy.mesh import registry as mesh_registry
from hydromodpy.model.boundaries.barriers import apply_flow_barriers_to_flow
from hydromodpy.model.boundaries.binder_payloads import payloads_as_mappings
from hydromodpy.model.boundaries.climate import (
    apply_etp_load_result_to_flow,
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.model.boundaries.lakes import (
    apply_cutoff_wall_to_flow,
    apply_lake_abacus_to_flow,
    apply_lake_bathymetry_to_flow,
    apply_lake_flux_forcings_to_flow,
    apply_lake_geometry_to_flow,
    apply_lake_meteo_forcings_to_flow,
)
from hydromodpy.model.boundaries.streams import (
    apply_runoff_to_sfr_networks,
    apply_sfr_network_to_flow,
    sfr_routes_catchment_runoff,
)
from hydromodpy.model.domain.structure_binders import apply_geology_to_domain
from hydromodpy.model.flow import Flow
from hydromodpy.model.forcing import soil_stored
from hydromodpy.model.forcing.soil_budget import gauged_discharge_line, soil_budget_lines
from hydromodpy.model.forcing.soil_config import (
    soil_reservoir_of,
    spinup_refusal,
    steady_start_refusal,
)
from hydromodpy.model.forcing.soil_forcing import compute_soil_forcings, ru_ladder
from hydromodpy.model.forcing.soil_grids import load_forcing_grid, window_days
from hydromodpy.results.products.key import array_digest, product_key
from hydromodpy.workflow.products import ask
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
    from hydromodpy.data import DataLoader

    return DataLoader(*args, **kwargs)


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

    Runtime loading is delegated to ``DataLoader`` in the
    data.loading package. Structural bindings are then applied explicitly
    through domain/process binder modules.
    """
    data_plan = ctx.data_plan
    loader = _build_data_runtime_loader(
        config_path=ctx.config_path,
        data_plan=data_plan,
        bounds=ctx.bounds,
        locked=getattr(ctx.setup, "locked_inputs", None),
    )
    loader.load_all(ctx)
    check_run_gauge_area(
        getattr(ctx.cfg, "site", None),
        ctx.loaded_data.hydrometry,
        getattr(ctx.setup.geographic, "catch_area", None),
        bounds=ctx.bounds if ctx.bounds is not None else Bounds(),
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


def ensure_flow(state: WorkflowContext) -> None:
    """Create ``state.setup.flow`` from ``state.cfg.flow`` when missing."""
    if state.setup.flow is None:
        state.setup.flow = Flow(config=state.cfg.flow)


def rebind_flow_if_stale(run_state: WorkflowContext) -> bool:
    """Rebuild ``setup.flow`` when another configuration built it, with its forcings.

    A Project builds its model phase once and drives several runs through it, so
    a sweep point, or a plain run after an overridden one, arrives with a ``flow``
    section the live flow was not built from. The new flow goes through the binder
    cascade of the data step, so it keeps every forcing (lake meteo and flux,
    runoff to SFR, ETP, oceanic) the data step gave the former one. Before the data
    are loaded there is nothing to bind: the data step does it.

    The frozen ``setup.model`` was built from the former flow, so it is reset too.

    Returns True when a rebuild happened.
    """
    setup_state = run_state.setup
    flow = setup_state.flow
    if flow is None or flow.config is run_state.cfg.flow:
        return False
    setup_state.flow = None
    setup_state.model = None
    if run_state.loaded_data.loaded_plan_types is None:
        ensure_flow(run_state)
    else:
        apply_structural_updates_from_data(run_state)
    return True


def _resolved_window(run_state: WorkflowContext):
    """The window the data load and the soil run on: the whole simulation, never one chain window."""
    for name in ("whole_time_grid", "time_grid"):
        resolved_grid = getattr(run_state.setup, name, None)
        if resolved_grid is not None:
            return resolved_grid.window
    return resolve_simulation_time_window(run_state.cfg)


def _lumped_catchment_polygon(run_state: WorkflowContext):
    """The catchment as one polygon in the model CRS under a lumped mesh engine, else None.

    A spatial forcing is averaged over the one cell of a lumped mesh. A meshed backend
    keeps the period view, so it gets no polygon.
    """
    engine = getattr(getattr(run_state.cfg, "mesh", None), "engine", None)
    if engine is None or not mesh_registry.mesh_engines.get(engine).capabilities.lumped:
        return None
    geographic = run_state.setup.geographic
    outline = catchment_outline(geographic)
    if outline is None:
        return None
    crs = getattr(geographic, "crs_proj", None)
    if outline.crs is not None and crs:
        outline = outline.to_crs(str(crs))
    return outline.geometry.union_all()


def _combined_digest(parts: list) -> str:
    """The sha256 of the array digests of ``parts``, in order."""
    digest = hashlib.sha256()
    for values in parts:
        digest.update(array_digest(values).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _soil_input_digests(run_state: WorkflowContext, window, model_crs: str, catchment) -> dict:
    """One digest per input of the soil step, computed once and kept on ``setup``.

    The precipitation and ETP digests read the same grids the soil reads, so
    the guards still run here and a missing or wrong grid is refused before the
    key is built. The soil capacity is a raster file, digested by its bytes. The
    catchment digest is the WKB of its outline in the model CRS.
    """
    data_state = run_state.loaded_data
    days = window_days(window)
    p_grid, p_x, p_y, p_time, _ = load_forcing_grid(
        data_state.precipitation,
        section="[data.precipitation]",
        family="precipitation",
        window=window,
        days=days,
        model_crs=model_crs,
    )
    e_grid, e_x, e_y, e_time, _ = load_forcing_grid(
        data_state.etp,
        section="[data.etp]",
        family="etp",
        window=window,
        days=days,
        model_crs=model_crs,
    )
    inputs = {
        "precipitation": _combined_digest([p_grid, p_x, p_y, p_time.values]),
        "etp": _combined_digest([e_grid, e_x, e_y, e_time.values]),
    }
    soil_capacity = getattr(data_state, "soil_capacity", None)
    if soil_capacity is not None:
        inputs["soil_capacity"] = _capacity_digest(soil_capacity)
    if catchment is not None:
        inputs["catchment"] = _catchment_digest(catchment, model_crs)
    return inputs


def _soil_sources(run_state: WorkflowContext, window, model_crs: str) -> tuple:
    """What the soil input digests were computed from.

    The loaded grids and the geographic are compared by identity, because a
    reload or a rebuild replaces them with new objects. The window and the CRS
    are compared by value. A fork shares the objects, so it hashes nothing.
    """
    data_state = run_state.loaded_data
    return (
        data_state.precipitation,
        data_state.etp,
        getattr(data_state, "soil_capacity", None),
        run_state.setup.geographic,
        (window.start.isoformat(), window.end.isoformat()),
        model_crs,
    )


def _same_sources(cached: tuple, current: tuple) -> bool:
    """True when ``current`` holds the very objects and values of ``cached``."""
    *cached_objects, cached_window, cached_crs = cached
    *current_objects, current_window, current_crs = current
    return (
        all(a is b for a, b in zip(cached_objects, current_objects, strict=True))
        and cached_window == current_window
        and cached_crs == current_crs
    )


def _capacity_digest(load_result) -> str:
    """The digest of a soil capacity raster: the bytes of its file, or its values."""
    record = load_result.fields[0]
    data = record.data
    if isinstance(data, (str, Path)):
        return sha256_of(data)
    values = data[record.variable].values
    return _combined_digest([values, data["x"].values, data["y"].values])


def _catchment_digest(catchment, model_crs: str) -> str:
    """The sha256 of the WKB of the catchment outline in the model CRS."""
    import shapely.wkb

    frame = catchment if catchment.crs is None else catchment.to_crs(model_crs)
    digest = hashlib.sha256()
    digest.update(shapely.wkb.dumps(frame.geometry.union_all()))
    return digest.hexdigest()


def _bind_soil_recharge_etp(run_state: WorkflowContext, window):
    """Compute or read the soil forcings, then bind recharge and ETP; return the soil."""
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
        model_crs = str(setup_state.geographic.crs_proj)
        catchment = catchment_outline(setup_state.geographic)
        sources = _soil_sources(run_state, window, model_crs)
        cached = setup_state.soil_product_inputs
        if cached is None or not _same_sources(cached[0], sources):
            cached = (sources, _soil_input_digests(run_state, window, model_crs, catchment))
            setup_state.soil_product_inputs = cached
        key = product_key(
            "soil",
            codec=soil_stored.SCHEMA_VERSION,
            package="model",
            inputs=cached[1],
            processing={
                "soil": soil_config.model_dump(mode="json"),
                "window": [window.start.isoformat(), window.end.isoformat()],
                "crs": model_crs,
            },
        )
        if setup_state.products.get("soil") == key and setup_state.soil_forcings is not None:
            soil = setup_state.soil_forcings
        else:
            soil = ask(
                run_state,
                "soil",
                key=key,
                build=lambda: compute_soil_forcings(
                    precipitation=data_state.precipitation,
                    etp=data_state.etp,
                    config=soil_config,
                    window=window,
                    model_crs=model_crs,
                    soil_capacity=getattr(data_state, "soil_capacity", None),
                    catchment=catchment,
                ),
                read=lambda directory: soil_stored.read_soil_forcings(
                    directory, like=data_state.precipitation, config=soil_config
                ),
            )
    setup_state.soil_forcings = soil

    apply_recharge_load_result_to_flow(
        flow=setup_state.flow,
        recharge_result=data_state.recharge if soil is None else soil.recharge,
        simulation_window=window,
        cell_polygon=_lumped_catchment_polygon(run_state),
    )
    apply_etp_load_result_to_flow(
        flow=setup_state.flow,
        etp_result=getattr(data_state, "etp", None) if soil is None else soil.residual_etp,
        simulation_window=window,
        from_soil_reservoir=soil is not None,
    )
    return soil


def _line_traces(
    run_state: WorkflowContext,
    declarations: dict,
    *,
    table: str,
    suffix: str,
    project_crs: object,
) -> dict:
    """Read the ``line_path`` trace of each declaration, keyed by its id.

    A ``line_path`` is written from the project root, as every user file since
    lot 4.3. A declaration with inline ``line`` coordinates, ``auto`` or no
    path reads nothing here, and its binder resolves it.
    """
    from hydromodpy.core.toml_io.paths import resolve_declared_path
    from hydromodpy.data.ingest.line_trace import read_line_trace

    traces: dict = {}
    if not declarations:
        return traces
    root = getattr(getattr(run_state.cfg, "workspace", None), "project_root", None)
    config_path = getattr(run_state, "config_path", None)
    if root is None and config_path is not None:
        root = Path(config_path).parent
    for key, cfg in declarations.items():
        if cfg is None or (isinstance(cfg, dict) and "line" in cfg and "barrier" in cfg):
            continue
        line_path = getattr(cfg, "line_path", None)
        if not line_path or getattr(cfg, "line", None) or bool(getattr(cfg, "auto", False)):
            continue
        path = resolve_declared_path(str(line_path), base_dir=Path(root) if root else Path.cwd())
        traces[str(key)] = read_line_trace(
            path,
            where=f"flow.sinks_sources.{table}.{key}{suffix}",
            project_crs=project_crs,
        )
    return traces


def _bind_lakes_and_structures(run_state: WorkflowContext, window) -> None:
    """Bind the lake geometry and flux forcings, the cutoff wall and the flow barriers."""
    setup_state = run_state.setup
    data_state = run_state.loaded_data
    # The lake readers match each loaded record to a lake id, and the binders
    # attach what they return, so a lake without a record keeps its payload.
    lake_ids = list(payloads_as_mappings(setup_state.flow, "lakes"))
    if lake_ids:
        apply_lake_geometry_to_flow(
            flow=setup_state.flow,
            polygons=lake_polygons(getattr(data_state, "lake_geometry", None), lake_ids),
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
        cutoff_wall_traces=_line_traces(
            run_state,
            {
                lake_id: payload.get("cutoff_wall")
                for lake_id, payload in payloads_as_mappings(setup_state.flow, "lakes").items()
            },
            table="lakes",
            suffix=".cutoff_wall",
            project_crs=project_crs,
        ),
    )
    sinks_sources = getattr(setup_state.flow, "sinks_sources", None) or {}
    apply_flow_barriers_to_flow(
        flow=setup_state.flow,
        project_crs=project_crs,
        barrier_traces=_line_traces(
            run_state,
            dict(sinks_sources.get("flow_barriers") or {}),
            table="flow_barriers",
            suffix="",
            project_crs=project_crs,
        ),
    )
    if lake_ids:
        apply_lake_abacus_to_flow(
            flow=setup_state.flow,
            abacus=lake_abacus(getattr(data_state, "lake_abacus", None), lake_ids),
        )
        apply_lake_bathymetry_to_flow(
            flow=setup_state.flow,
            bathymetry=lake_bathymetry(getattr(data_state, "lake_bathymetry", None), lake_ids),
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
