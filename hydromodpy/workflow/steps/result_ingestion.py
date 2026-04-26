"""Result-ingestion step - ingest solver outputs and save run artifacts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.simulation.planning.plan import ProcessRun, RunExecutionResult
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


def step_ingest_run_results(
    ctx: WorkflowContext,
    run: ProcessRun,
    result: RunExecutionResult,
) -> None:
    """Ingest solver outputs into ``ctx.store`` after one run completes."""
    if ctx.store is None:
        return

    from hydromodpy.simulation.extraction.post_run import post_run_results

    results_cfg = ctx.cfg.simulation.results
    post_run_results(
        sim_id=ctx.sim_id,
        solver_name=run.solver,
        solver_output_dir=result.solver_output_dir,
        results_config=results_cfg,
        store=ctx.store,
        keep_solver_files=True,
        run_id=ctx.setup.run_id,
    )


def step_write_provenance(ctx: WorkflowContext) -> None:
    """Record provenance fingerprints for each loaded data variable."""
    if ctx.store is None or ctx.sim_id is None:
        return

    import dataclasses

    import numpy as np

    loaded = ctx.loaded_data
    written = 0
    for f in dataclasses.fields(loaded):
        load_result = getattr(loaded, f.name, None)
        if load_result is None:
            continue

        # PointRecord items (timeseries)
        points = getattr(load_result, "points", None)
        if points:
            for rec in points:
                try:
                    arr = np.asarray(rec.data["value"].values, dtype="float64")
                    ctx.store.write_provenance(
                        ctx.sim_id,
                        variable=f"{f.name}:{rec.variable}",
                        source_ref=str(getattr(rec, "source", "")),
                        data=arr,
                        source_type="data_manager",
                        period_start=getattr(rec, "date_start", None),
                        period_end=getattr(rec, "date_end", None),
                    )
                    written += 1
                except Exception:
                    logger.debug("Provenance failed for %s:%s", f.name, rec.variable)

        # FieldRecord items (gridded data)
        fields = getattr(load_result, "fields", None)
        if fields:
            for rec in fields:
                try:
                    data = rec.data
                    if hasattr(data, "values"):
                        # xarray Dataset: take first data variable
                        var_name = list(data.data_vars)[0] if data.data_vars else None
                        if var_name is not None:
                            arr = np.asarray(data[var_name].values, dtype="float64")
                        else:
                            continue
                    else:
                        continue
                    ctx.store.write_provenance(
                        ctx.sim_id,
                        variable=f"{f.name}:{rec.variable}",
                        source_ref=str(getattr(rec, "source", "")),
                        data=arr,
                        source_type="data_manager",
                        period_start=getattr(rec, "date_start", None),
                        period_end=getattr(rec, "date_end", None),
                    )
                    written += 1
                except Exception:
                    logger.debug("Provenance failed for field %s:%s", f.name, rec.variable)

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

    import dataclasses
    import json
    from pathlib import Path

    import numpy as np
    import pandas as pd

    sz = ctx.store.open_zarr(ctx.sim_id)
    loaded = ctx.loaded_data
    written = 0

    for f in dataclasses.fields(loaded):
        obj = getattr(loaded, f.name, None)
        if obj is None:
            continue

        # GeologyField: encoded raster + zone mapping + transform
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

                # Persist per-cell zone assignment if mesh is available
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

        # HydrographyResult: stream raster
        if hasattr(obj, "streams_array"):
            try:
                arr = np.asarray(obj.streams_array)
                if arr.size > 0:
                    sz.write_forcing_field(
                        "hydrography_streams",
                        arr,
                        unit="",
                        source="hydrography",
                    )
                    written += 1
            except Exception:
                logger.debug("Failed to persist hydrography forcing")
            continue

        # Standard LoadResult with points and fields
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


def step_save_run_artifacts(
    ctx: WorkflowContext,
    wall_seconds: float,
) -> None:
    """Save config snapshot and optional capability gallery."""
    from hydromodpy.core.config.toml_write import dumps as dump_toml_text

    project_root = ctx.setup.workspace.project_root

    # Config snapshot
    snapshot_path = project_root / "_config_snapshot.toml"
    try:
        snapshot_path.write_text(dump_toml_text(ctx.raw_toml), encoding="utf-8")
    except Exception:
        pass

    # Capability gallery
    gallery_cfg = getattr(ctx.cfg, "capability_gallery", None)
    if gallery_cfg is not None and getattr(gallery_cfg, "enabled", False):
        from hydromodpy.analysis.capability_gallery import (
            publish_run_to_capability_gallery,
        )

        plan = ctx.execution.simulation_plan
        solvers_used = {r.solver for r in plan.runs} if plan is not None else set()

        run_wrapper = None
        if ctx.store is not None and ctx.sim_id is not None:
            try:
                from hydromodpy.results.run import Run as _Run

                run_wrapper = _Run(ctx.sim_id, ctx.store)
            except Exception:
                run_wrapper = None

        publish_run_to_capability_gallery(
            run_id=str(ctx.setup.run_id),
            run_folder=project_root,
            config=gallery_cfg,
            solvers=tuple(str(s) for s in solvers_used),
            run=run_wrapper,
        )
