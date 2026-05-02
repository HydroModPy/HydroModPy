"""Prepare-solver step - build the plan, open the store, persist inputs."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError, MeshError, PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import OpenStoreState, PipelineState, SetupState

if TYPE_CHECKING:
    from hydromodpy.physics.flow import Flow
    from hydromodpy.results.catalog.protocol import SimulationStore
    from hydromodpy.simulation.planning.plan import SimulationPlan
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.workflow.context import WorkflowContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Persistence helpers (mesh, parameters, geographic rasters)
# ---------------------------------------------------------------------------


def step_persist_params(
    store: SimulationStore,
    sim_id: str,
    flow: Flow,
    *,
    domain: Domain | None = None,
) -> None:
    """Write hydraulic parameters from a Flow object into the catalog.

    Also persists the domain aquifer thickness (from domain.depth_model) as a
    global scalar, since it is a calibratable quantity listed alongside K/Sy/Ss.
    """
    params: list[dict] = []

    params_dict = getattr(flow, "parameters", None)
    if params_dict:
        for pid, fp in params_dict.items():
            kind = getattr(fp, "kind", "homogeneous")
            if kind == "homogeneous":
                params.append(
                    {
                        "param_name": pid,
                        "zone_id": None,
                        "value": getattr(fp, "value", None),
                        "unit": getattr(fp, "unit", ""),
                        "parameterization": "homogeneous",
                    }
                )
            else:
                values_by_key = getattr(fp, "values_by_key", None) or {}
                for zone_key, val in values_by_key.items():
                    params.append(
                        {
                            "param_name": pid,
                            "zone_id": str(zone_key),
                            "value": val,
                            "unit": getattr(fp, "unit", ""),
                            "parameterization": "geology_mapped",
                        }
                    )

    if domain is not None:
        depth_model = getattr(domain, "depth_model", None)
        thickness = getattr(depth_model, "thickness", None) if depth_model else None
        if thickness is not None:
            params.append(
                {
                    "param_name": "thickness",
                    "zone_id": None,
                    "value": float(thickness),
                    "unit": "m",
                    "parameterization": "homogeneous",
                }
            )

    if params:
        store.write_parameters(sim_id, params)


def step_persist_mesh(ctx: WorkflowContext, sim_id: str) -> None:
    """Write mesh topology into the simulation's Zarr.

    The mesh is always materialised as a :class:`HydroMesh`: an explicit
    Gmsh planar mesh when one is loaded, or a structured-from-DEM mesh
    derived from ``domain.surface_topo.support`` otherwise. Lumped
    simulations (no Domain attached, e.g. GR4J) are skipped: there is no
    spatial discretisation to persist.

    Layer interfaces come from ``Domain.z_interfaces``, derived from the
    topographic surface and the configured depth model.
    """
    import numpy as np

    domain = ctx.setup.domain
    if domain is None:
        return

    z_intf = np.asarray(domain.z_interfaces, dtype=float)

    mesh_planar = ctx.setup.mesh_planar
    if mesh_planar is not None:
        vertices = mesh_planar.points_xy
        connectivity = mesh_planar.connectivity
    else:
        from hydromodpy.spatial.mesh.grid_wrappers import RegularGrid

        support = getattr(domain.surface_topo, "support", None)
        if support is None or support.nrows is None or support.ncols is None:
            raise MeshError(
                "step_persist_mesh: no Gmsh planar mesh and no raster support "
                "on domain.surface_topo - cannot materialise a HydroMesh"
            )
        regular = RegularGrid(
            shape=(int(support.nrows), int(support.ncols)),
            dx=float(support.dx),
            dy=float(support.dy),
            origin=(float(support.xmin), float(support.ymax)),
            n_layers=max(int(z_intf.size) - 1, 1),
            crs=str(support.crs) if support.crs is not None else None,
        )
        hydro_mesh = regular.to_hydro_mesh()
        vertices = hydro_mesh.vertices
        connectivity = hydro_mesh.flat_connectivity

    ctx.store.write_mesh(
        sim_id,
        vertices=vertices,
        face_node_connectivity=connectivity,
        z_interfaces=z_intf,
    )


def step_persist_geographic(ctx: WorkflowContext, sim_id: str) -> None:
    """Persist the geographic rasters (DEM, watershed masks) into the Zarr."""
    from hydromodpy.spatial.geographic.store_ingestion import (
        persist_geographic_to_store,
    )

    if ctx.setup.geographic is None:
        return
    persist_geographic_to_store(ctx.setup.geographic, ctx.store, sim_id=sim_id)


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------


def collect_registration_kwargs(ctx: WorkflowContext) -> dict:
    """Gather all available metadata from ctx for register_simulation()."""
    kwargs: dict = {"flow_regime": ctx.cfg.flow.flow_regime}

    if getattr(ctx, "config_path", None) is not None:
        kwargs["config_source"] = str(ctx.config_path)

    kwargs["config"] = ctx.cfg.model_dump(mode="json")
    kwargs["config_snapshot"] = collect_effective_config_snapshot(ctx)

    mesh = ctx.setup.mesh_planar
    if mesh is not None:
        kwargs["n_cells"] = mesh.n_cells
        kwargs["mesh_type"] = getattr(mesh, "cell_type", None)
        kwargs["cell_types"] = [getattr(mesh, "cell_type", "unknown")]
        bbox = getattr(mesh, "bounds", None)
        if bbox is not None:
            kwargs["bbox"] = list(bbox)
        try:
            mesh_bytes = mesh.points_xy.tobytes() + mesh.connectivity.tobytes()
            kwargs["mesh_hash"] = hashlib.sha256(mesh_bytes).hexdigest()
        except Exception:
            pass

    crs = getattr(ctx.cfg.geographic, "crs_project", None)
    if crs is not None:
        kwargs["crs"] = str(crs)

    tg = ctx.setup.time_grid
    if tg is not None:
        boundaries = getattr(tg, "boundaries", None)
        if boundaries and len(boundaries) >= 2:
            kwargs["period_start"] = str(boundaries[0])
            kwargs["period_end"] = str(boundaries[-1])
            kwargs["n_timesteps"] = len(boundaries) - 1
        else:
            datetimes = getattr(tg, "datetimes", None)
            if datetimes:
                start_datetime = getattr(tg, "start_datetime", None)
                kwargs["period_start"] = str(
                    start_datetime if start_datetime is not None else datetimes[0]
                )
                kwargs["period_end"] = str(datetimes[-1])
                kwargs["n_timesteps"] = len(datetimes)
        time_cfg = getattr(ctx.cfg.simulation, "time", None)
        if time_cfg is not None:
            kwargs["time_unit"] = getattr(time_cfg, "step_unit", None)

    return kwargs


def collect_effective_config_snapshot(ctx: WorkflowContext) -> dict:
    """Return the reproducible config snapshot used by the current run."""
    payload = ctx.cfg.model_dump(mode="json")

    effective_results = getattr(ctx, "effective_results_config", None)
    if effective_results is not None:
        simulation_payload = dict(payload.get("simulation") or {})
        simulation_payload["results"] = effective_results.model_dump(mode="json")
        payload["simulation"] = simulation_payload

    domain = getattr(ctx.setup, "domain", None)
    domain_config = getattr(domain, "config", None)
    if domain_config is not None and hasattr(domain_config, "model_dump"):
        payload["domain"] = domain_config.model_dump(mode="json")

    return payload


def _crs_grid_mapping_attrs(crs: object) -> dict[str, object]:
    """Return CF grid-mapping attrs for a CRS value."""
    try:
        from pyproj import CRS

        parsed = CRS.from_user_input(crs)
        attrs = dict(parsed.to_cf())
        if "crs_wkt" not in attrs:
            attrs["crs_wkt"] = parsed.to_wkt()
        epsg = parsed.to_epsg()
        if epsg is not None:
            attrs["epsg_code"] = int(epsg)
        return attrs
    except Exception:
        return {"crs_wkt": str(crs)}


def _write_zarr_crs(ctx: WorkflowContext, sim_id: str) -> None:
    """Persist CRS metadata in the simulation Zarr store when configured."""
    geographic_cfg = getattr(ctx.cfg, "geographic", None)
    crs = getattr(geographic_cfg, "crs_project", None)
    if crs is None:
        return
    attrs = _crs_grid_mapping_attrs(crs)
    epsg_raw = attrs.get("epsg_code")
    semi_major_raw = attrs.get("semi_major_axis")
    inverse_flattening_raw = attrs.get("inverse_flattening")
    ctx.store.write_crs(
        sim_id,
        crs_wkt=str(attrs.get("crs_wkt", str(crs))),
        grid_mapping_name=str(attrs.get("grid_mapping_name", "latitude_longitude")),
        epsg_code=int(epsg_raw) if epsg_raw is not None else None,
        semi_major_axis=float(semi_major_raw) if semi_major_raw is not None else None,
        inverse_flattening=(
            float(inverse_flattening_raw) if inverse_flattening_raw is not None else None
        ),
    )


def _write_zarr_time(ctx: WorkflowContext, sim_id: str) -> None:
    """Persist simulation period-end timestamps as CF time coordinates."""
    time_grid = getattr(ctx.setup, "time_grid", None)
    boundaries = getattr(time_grid, "boundaries", None)
    import numpy as np
    import pandas as pd

    if boundaries and len(boundaries) >= 2:
        period_ends = pd.DatetimeIndex(boundaries[1:])
    else:
        datetimes = getattr(time_grid, "datetimes", None)
        if not datetimes:
            return
        period_ends = pd.DatetimeIndex(datetimes)
    if period_ends.tz is None:
        period_ends = period_ends.tz_localize("UTC")
    else:
        period_ends = period_ends.tz_convert("UTC")
    epoch = pd.Timestamp("1970-01-01T00:00:00Z")
    seconds = ((period_ends - epoch).total_seconds()).astype("int64")
    ctx.store.write_time(
        sim_id,
        np.asarray(seconds, dtype="int64"),
        epoch="1970-01-01T00:00:00Z",
        units="seconds since 1970-01-01T00:00:00Z",
    )


def step_register_simulation(
    ctx: WorkflowContext,
    sim_id: str,
    *,
    plan: SimulationPlan,
    project_name: str,
    name: str,
) -> str:
    """Register the simulation in the catalog and return the final run name.

    The catalog may rename a run on collision. The returned value is the name
    recorded on disk; callers should use it from here on.
    """
    reg_kwargs = collect_registration_kwargs(ctx)
    if ctx.parent_sim_id is not None:
        reg_kwargs["parent_sim_id"] = ctx.parent_sim_id

    solvers = ",".join(r.solver for r in plan.runs)
    registration = ctx.store.register_simulation(
        sim_id,
        project=project_name,
        solver=solvers,
        name=name,
        on_collision=ctx.cfg.simulation.on_collision,
        **reg_kwargs,
    )
    final_name = registration.name or name
    replaced = registration.replaced_sim_id
    short = sim_id[:8]
    if replaced:
        logger.info("Run '%s' stored [%s] (replaced %s)", final_name, short, replaced[:8])
    else:
        logger.info("Run '%s' stored [%s]", final_name, short)
    if registration.zarr is not None:
        registration.zarr.close()
    _write_zarr_time(ctx, sim_id)
    _write_zarr_crs(ctx, sim_id)

    try:
        project_root = getattr(getattr(ctx.setup, "workspace", None), "project_root", None)
        rng_seed = getattr(ctx.cfg.simulation, "rng_seed", None)
        ctx.store.write_run_environment(
            sim_id,
            project_root=project_root,
            rng_seed=rng_seed,
        )
    except Exception:
        logger.exception("Failed to capture run environment for sim %s", short)
    return final_name


# ---------------------------------------------------------------------------
# Store opening
# ---------------------------------------------------------------------------


def _register_tracked_input_files(ctx: WorkflowContext) -> None:
    """Walk the config tree and persist every InputFile-marked path."""
    from hydromodpy.core.tracking import collect_input_files

    try:
        entries = collect_input_files(ctx.cfg)
    except Exception as exc:
        logger.warning("Skipping tracked-file registration: %s", exc)
        return

    portable = [e for e in entries if e.portable]
    if not portable:
        return
    written = ctx.store.register_tracked_files(ctx.sim_id, portable)
    logger.info(
        "Registered %d tracked input file(s) for simulation %s",
        written,
        ctx.sim_id,
    )


def step_open_store(ctx: WorkflowContext) -> None:
    """Open a ``SimulationCatalog`` and register the current simulation.

    Does nothing when the effective ``simulation.results.persistence`` block
    disables catalog persistence. After this step ``ctx.store`` and
    ``ctx.sim_id`` are set.
    """
    results_cfg = getattr(ctx, "effective_results_config", None) or ctx.cfg.simulation.results
    if not results_cfg.persistence.save_catalog:
        return

    from uuid import uuid4

    from hydromodpy.results.catalog import SimulationCatalog

    workspace = ctx.setup.workspace
    ctx.store = SimulationCatalog.from_workspace(
        workspace,
        persistence=results_cfg.persistence,
        register_global=True,
    )
    ctx.sim_id = str(uuid4())

    project_name = workspace.project_root.name
    plan = ctx.execution.simulation_plan

    reg_kwargs = collect_registration_kwargs(ctx)
    if ctx.parent_sim_id is not None:
        reg_kwargs["parent_sim_id"] = ctx.parent_sim_id
    on_collision = getattr(ctx.cfg.simulation, "on_collision", "replace")
    registration = ctx.store.register_simulation(
        ctx.sim_id,
        project=project_name,
        solver=",".join(r.solver for r in plan.runs),
        name=ctx.setup.run_id,
        on_collision=on_collision,
        **reg_kwargs,
    )
    if registration.name and registration.name != ctx.setup.run_id:
        ctx.setup.run_id = registration.name
    if registration.zarr is not None:
        registration.zarr.close()
    _write_zarr_time(ctx, ctx.sim_id)
    _write_zarr_crs(ctx, ctx.sim_id)

    try:
        project_root = getattr(workspace, "project_root", None)
        rng_seed = getattr(ctx.cfg.simulation, "rng_seed", None)
        ctx.store.write_run_environment(
            ctx.sim_id,
            project_root=project_root,
            rng_seed=rng_seed,
        )
    except Exception:
        logger.exception("Failed to capture run environment for sim %s", ctx.sim_id[:8])

    _register_tracked_input_files(ctx)

    if ctx.setup.flow is not None:
        step_persist_params(
            ctx.store,
            ctx.sim_id,
            ctx.setup.flow,
            domain=ctx.setup.domain,
        )

    step_persist_mesh(ctx, ctx.sim_id)
    step_persist_geographic(ctx, ctx.sim_id)


# ---------------------------------------------------------------------------
# Provenance and forcings persistence
# ---------------------------------------------------------------------------


def _record_source_path(record: object) -> Path | None:
    file_path = getattr(record, "file_path", None)
    if file_path is not None:
        return Path(file_path)
    data = getattr(record, "data", None)
    if isinstance(data, (str, Path)):
        return Path(data)
    return None


def _sha256_file_or_none(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _loader_name(scope_name: str, record: object) -> str:
    return f"{scope_name}:{type(record).__name__}"


def step_write_provenance(ctx: WorkflowContext) -> None:
    """Record provenance fingerprints for each loaded data variable."""
    if ctx.store is None or ctx.sim_id is None:
        return

    import numpy as np

    loaded = ctx.loaded_data
    written = 0
    for f in dataclasses.fields(loaded):
        load_result = getattr(loaded, f.name, None)
        if load_result is None:
            continue

        points = getattr(load_result, "points", None)
        if points:
            for rec in points:
                try:
                    arr = np.asarray(rec.data["value"].values, dtype="float64")
                    source_path = _record_source_path(rec)
                    ctx.store.write_provenance(
                        ctx.sim_id,
                        variable=f"{f.name}:{rec.variable}",
                        source_ref=str(getattr(rec, "source", "")),
                        data=arr,
                        source_type="data_manager",
                        source_sha256=_sha256_file_or_none(source_path),
                        loader_name=_loader_name(f.name, rec),
                        loader_version="v1",
                        period_start=getattr(rec, "date_start", None),
                        period_end=getattr(rec, "date_end", None),
                    )
                    written += 1
                except Exception as exc:
                    raise PipelineError(f"Provenance failed for {f.name}:{rec.variable}") from exc

        fields = getattr(load_result, "fields", None)
        if fields:
            for rec in fields:
                try:
                    data = rec.data
                    source_path = _record_source_path(rec)
                    if hasattr(data, "values"):
                        var_name = list(data.data_vars)[0] if data.data_vars else None
                        if var_name is not None:
                            arr = np.asarray(data[var_name].values, dtype="float64")
                        else:
                            continue
                    elif source_path is not None and source_path.is_file():
                        arr = np.frombuffer(source_path.read_bytes(), dtype="uint8")
                    else:
                        continue
                    ctx.store.write_provenance(
                        ctx.sim_id,
                        variable=f"{f.name}:{rec.variable}",
                        source_ref=str(getattr(rec, "source", "")),
                        data=arr,
                        source_type="data_manager",
                        source_sha256=_sha256_file_or_none(source_path),
                        loader_name=_loader_name(f.name, rec),
                        loader_version="v1",
                        period_start=getattr(rec, "date_start", None),
                        period_end=getattr(rec, "date_end", None),
                    )
                    written += 1
                except Exception as exc:
                    raise PipelineError(
                        f"Provenance failed for field {f.name}:{rec.variable}"
                    ) from exc

    if written:
        logger.info("Wrote %d provenance records for sim %s", written, ctx.sim_id)


def step_persist_forcings(ctx: WorkflowContext) -> None:
    """Persist input forcings into the Zarr ``forcing/`` group.

    Makes each simulation self-contained: the raw input timeseries and
    static fields are embedded alongside the results so the simulation
    can be reproduced without the original data files.

    Handles three data shapes from LoadedDataContext:

    - ``LoadResult`` with ``.points`` (PointRecord timeseries) and
      ``.fields`` (FieldRecord grids) - most variables
    - ``GeologyField`` - encoded raster + zone mapping
    - ``HydrographyResult`` - stream raster array
    """
    if ctx.store is None or ctx.sim_id is None:
        return

    import numpy as np
    import pandas as pd

    sz = ctx.store.open_zarr(ctx.sim_id)
    loaded = ctx.loaded_data
    written = 0

    for f in dataclasses.fields(loaded):
        obj = getattr(loaded, f.name, None)
        if obj is None:
            continue

        if hasattr(obj, "encoded_codes") and hasattr(obj, "encoded_to_zone"):
            try:
                codes = np.asarray(obj.encoded_codes)
                sz.write_forcing_field(
                    "geology_codes",
                    codes,
                    unit="",
                    source=getattr(obj, "source_kind", "raster"),
                )
                forcing = sz.root.require_group("forcing")
                geo_grp = forcing.require_group("geology_meta")
                geo_grp.attrs["zone_mapping"] = json.dumps(
                    {str(k): str(v) for k, v in obj.encoded_to_zone.items()}
                )
                geo_grp.attrs["zone_keys"] = list(obj.zone_keys)
                transform = getattr(obj, "transform", None)
                if transform is not None:
                    geo_grp.attrs["transform"] = list(float(v) for v in transform)[:6]
                if obj.crs is not None:
                    geo_grp.attrs["crs"] = str(obj.crs)
                geo_grp.attrs["cell_samples_per_axis"] = int(
                    getattr(obj, "default_cell_samples_per_axis", 8)
                )
                geo_grp.attrs["source_kind"] = str(getattr(obj, "source_kind", "raster"))

                mesh = getattr(ctx, "setup", None)
                mesh_planar = getattr(mesh, "mesh_planar", None) if mesh else None
                if mesh_planar is not None:
                    try:
                        disc = obj.on_mesh(mesh_planar)
                        fractions = getattr(disc, "fractions_by_zone", {})
                        for zone_key, frac_array in fractions.items():
                            safe_key = zone_key.replace("/", "_").replace(" ", "_")
                            sz.write_forcing_field(
                                f"geology_frac_{safe_key}",
                                np.asarray(frac_array, dtype="float64"),
                                unit="fraction",
                                source=f"geology:{zone_key}",
                            )
                        written += 1
                    except Exception:
                        logger.debug("Failed to persist geology zone fractions")

                written += 1
            except Exception:
                logger.debug("Failed to persist geology forcing")
            continue

        if hasattr(obj, "streams_array"):
            try:
                arr = np.asarray(obj.streams_array)
                if arr.size > 0:
                    from hydromodpy.spatial.geographic.core.hydrographic_network import (
                        HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
                    )

                    sz.write_forcing_field(
                        HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
                        arr,
                        unit="",
                        source="hydrography",
                    )
                    written += 1
                _persist_reference_hydrographic_feature(ctx, obj)
            except Exception:
                logger.debug("Failed to persist hydrography forcing")
            continue

        points = getattr(obj, "points", None)
        if points:
            for rec in points:
                try:
                    df = rec.data
                    timestamps = pd.to_datetime(df["datetime"]).values
                    values = df["value"].values.astype("float64")
                    station = getattr(rec, "station_id", None) or f.name
                    sz.write_forcing_timeseries(
                        f.name,
                        station,
                        timestamps,
                        values,
                        unit=getattr(rec, "unit", ""),
                        source=getattr(rec, "source", ""),
                    )
                    written += 1
                except Exception:
                    logger.debug(
                        "Failed to persist forcing %s:%s", f.name, getattr(rec, "station_id", "?")
                    )

        fields_list = getattr(obj, "fields", None)
        if fields_list:
            for rec in fields_list:
                try:
                    data = rec.data
                    if isinstance(data, (str, Path)):
                        continue
                    if hasattr(data, "data_vars"):
                        var_name = list(data.data_vars)[0] if data.data_vars else None
                        if var_name is None:
                            continue
                        arr = np.asarray(data[var_name].values, dtype="float64")
                    elif hasattr(data, "values"):
                        arr = np.asarray(data.values, dtype="float64")
                    else:
                        continue
                    sz.write_forcing_field(
                        f"{f.name}_{rec.variable}",
                        arr,
                        unit=getattr(rec, "unit", ""),
                        source=getattr(rec, "source", ""),
                    )
                    written += 1
                except Exception:
                    logger.debug(
                        "Failed to persist forcing field %s:%s",
                        f.name,
                        getattr(rec, "variable", "?"),
                    )

    if written:
        logger.info("Persisted %d forcing datasets for sim %s", written, ctx.sim_id)


def _persist_reference_hydrographic_feature(
    ctx: WorkflowContext,
    hydrography_result: object,
) -> bool:
    """Persist the imported hydrography vector as one canonical feature."""
    if ctx.store is None or ctx.sim_id is None:
        return False

    from pathlib import Path

    from hydromodpy.spatial.geographic.core.hydrographic_network import (
        HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        HydrographicNetwork,
    )

    features = getattr(getattr(ctx, "setup", None), "geographic_features", None)
    network = (
        getattr(features, "reference_hydrographic_network", None) if features is not None else None
    )
    if network is None:
        network = HydrographicNetwork.from_hydrography_result(hydrography_result)

    vector_path = getattr(network, "vector_path", None)
    if vector_path in (None, "") or not Path(str(vector_path)).exists():
        return False

    try:
        gdf = network.read_vector()
        if gdf is None or gdf.empty:
            return False
        if gdf.crs is None and getattr(network, "crs", None) not in (None, ""):
            gdf = gdf.set_crs(str(network.crs), allow_override=True)
        ctx.store.write_geographic_feature(
            ctx.sim_id,
            HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
            gdf,
        )
        return True
    except Exception:
        logger.debug("Failed to persist hydrographic network reference feature")
        return False


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class PrepareSolverStep:
    """Build the simulation plan + open the store."""

    name = "prepare_solver"
    tin: ClassVar[type] = SetupState
    tout: ClassVar[type] = OpenStoreState
    config_sections: ClassVar[tuple[str, ...]] = (
        "flow",
        "transport",
        "solver",
        "modflownwt",
        "modflow6",
    )

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.simulation.planning.planner import SimulationPlanner
        from hydromodpy.workflow.steps.planning import step_configure_results

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("PrepareSolverStep requires 'ctx' in state.data")

        if ctx.execution.simulation_plan is None:
            sim_cfg = getattr(ctx.cfg, "simulation", None)
            if sim_cfg is not None:
                ctx.execution.simulation_plan = SimulationPlanner().build(sim_cfg)

        if ctx.execution.simulation_plan is not None:
            ctx.effective_results_config = step_configure_results(
                ctx.cfg.simulation.results,
                ctx.execution.simulation_plan,
            )

        if not ctx.execution.lightweight:
            step_open_store(ctx)

            if ctx.store is not None:
                step_write_provenance(ctx)
                step_persist_forcings(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
