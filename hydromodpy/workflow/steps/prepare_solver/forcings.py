"""Concern 5 of PrepareSolverStep: persisting the input forcings of a run.

:func:`step_persist_forcings` writes every loaded forcing family into the
Zarr ``forcing/`` group: the geology codes and zone fractions, the reference
hydrography, the station series, the gridded fields, the watershed mean of a
gridded runoff or recharge, and the soil-reservoir columns.

A write that fails is either logged as a warning (the run then lacks data
something reads back) or ignored with a comment saying why; none is silent
without a reason.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.model.forcing.forcing_bridge import scaled_load_result
from hydromodpy.model.properties.zone_fractions import zone_fractions
from hydromodpy.model.sinks_sources.recharge import recharge_factor_of
from hydromodpy.results.storage.soil_tables import persist_soil_columns, soil_budget_rows
from hydromodpy.workflow.steps.prepare_solver.prepare import field_data_array

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.catalog.protocol import SimulationStore
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

logger = get_logger(__name__)

# Gridded forcing families reduced to a watershed-mean station series at
# persist time. The catchment discharge derivation reads runoff back from
# Zarr forcing/ when no stream network routes it.
_WATERSHED_MEAN_FORCINGS = frozenset({"runoff", "recharge"})


def watershed_mean_series(load_result: object):
    """Reduce a gridded forcing family to one tz-naive watershed-mean series.

    None when the reduction has nothing to reduce. Its refusals, such as a day
    without any valid pixel, propagate and stop the run.
    """
    import pandas as pd

    from hydromodpy.model.forcing.cells import spatial_mean_from_fields

    series = spatial_mean_from_fields(load_result)
    if series is None or len(series) == 0:
        return None
    idx = pd.DatetimeIndex(series.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    series.index = idx
    return series


def _hydrography_field_record(load_result: object) -> object | None:
    from hydromodpy.spatial.geographic.core.hydrographic_network import (
        HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    )

    for record in getattr(load_result, "fields", None) or ():
        if getattr(record, "variable", None) == HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME:
            return record
    return None


def _forcing_sources(ctx: WorkflowContext, soil: object | None) -> list[tuple[str, object]]:
    """Return the (family name, load result) pairs to persist, soil families included."""
    loaded = ctx.loaded_data
    sources = [(f.name, getattr(loaded, f.name, None)) for f in dataclasses.fields(loaded)]
    if soil is not None:
        # loaded.recharge and loaded.runoff are None in soil mode (R1, R2): no
        # duplicate key reaches the loop of the caller.
        sources += [("recharge", soil.recharge), ("runoff", soil.runoff)]
    return sources


def _persist_geology(sz: SimulationZarr, obj: object) -> int:
    """Write the geology codes and their zone mapping; return the datasets written."""
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
    except Exception:
        # Not ignorable: a run without its geology codes cannot say which zone
        # a cell belongs to when it is read back.
        logger.warning("Failed to persist geology forcing", exc_info=True)
        return 0
    return 1


def _persist_geology_fractions(ctx: WorkflowContext, sz: SimulationZarr, obj: object) -> int:
    """Write the zone fractions of every cell, or nothing without a cell mesh.

    The fractions are the ones the solvers map K, Sy and Ss with, not a second
    sampling: an error here is the solver's error, never swallowed.
    """
    cell_mesh = getattr(getattr(ctx, "setup", None), "cell_mesh", None)
    if cell_mesh is None:
        return 0
    fractions = zone_fractions(cell_mesh, obj)
    for zone_key, frac_array in fractions.by_zone().items():
        safe_key = zone_key.replace("/", "_").replace(" ", "_")
        sz.write_forcing_field(
            f"geology_frac_{safe_key}",
            np.asarray(frac_array, dtype="float64"),
            unit="fraction",
            source=f"geology:{zone_key}",
        )
    return 1


def _persist_hydrography(
    ctx: WorkflowContext, sz: SimulationZarr, obj: object, *, store: SimulationStore
) -> int:
    """Write the reference hydrography raster and vector; return the datasets written."""
    written = 0
    try:
        record = _hydrography_field_record(obj)
        if record is not None:
            arr = field_data_array(record)
            if arr is not None and arr.size > 0:
                from hydromodpy.spatial.geographic.core.hydrographic_network import (
                    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
                )

                sz.write_forcing_field(
                    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
                    arr,
                    unit=getattr(record, "unit", ""),
                    source=getattr(record, "source", ""),
                )
                written += 1
            _persist_reference_hydrographic_feature(ctx, obj, store=store)
    except Exception:
        # Ignorable: the reference hydrography is a comparison aid for the
        # network cards. The solve reads none of it, and a reader of the run
        # that finds it absent shows no reference network.
        logger.debug("Failed to persist hydrography forcing")
    return written


def _persist_points(sz: SimulationZarr, name: str, points: object) -> int:
    """Write each station series of one family; return the series written."""
    import pandas as pd

    written = 0
    for rec in points:
        try:
            df = rec.data
            timestamps = pd.to_datetime(df["datetime"]).values
            values = df["value"].values.astype("float64")
            station = getattr(rec, "station_id", None) or name
            sz.write_forcing_timeseries(
                name,
                station,
                timestamps,
                values,
                unit=getattr(rec, "unit", ""),
                source=getattr(rec, "source", ""),
            )
            written += 1
        except Exception:
            # Not ignorable: the station series is a forcing of the run and
            # the derivations read it back; its absence changes their result.
            logger.warning(
                "Failed to persist forcing %s:%s",
                name,
                getattr(rec, "station_id", "?"),
                exc_info=True,
            )
    return written


def _persist_fields(sz: SimulationZarr, name: str, fields_list: object) -> int:
    """Write each gridded field of one family; return the fields written."""
    written = 0
    for rec in fields_list:
        try:
            arr = field_data_array(rec)
            if arr is None:
                continue
            sz.write_forcing_field(
                f"{name}_{rec.variable}",
                arr,
                unit=getattr(rec, "unit", ""),
                source=getattr(rec, "source", ""),
            )
            written += 1
        except Exception:
            # Not ignorable: same reason as a station series, the field is a
            # forcing of the run.
            logger.warning(
                "Failed to persist forcing field %s:%s",
                name,
                getattr(rec, "variable", "?"),
                exc_info=True,
            )
    return written


def _persist_watershed_mean(sz: SimulationZarr, name: str, obj: object, fields_list: list) -> int:
    """Write the watershed mean of a gridded family as a station-shaped series.

    A gridded family has no station to land under forcing/<var>/<station>;
    its watershed mean keeps a station-shaped copy so post-processing
    (catchment discharge) can read the forcing back. Same reduction as the
    SFR / LAK forcing binders, so both accountings stay consistent.
    """
    series = watershed_mean_series(obj)
    if series is None:
        return 0
    try:
        sz.write_forcing_timeseries(
            name,
            CATCHMENT,
            np.asarray(series.index.values, dtype="datetime64[ns]"),
            series.to_numpy(dtype="float64"),
            unit=getattr(fields_list[0], "unit", "") or "",
            source="watershed_mean",
        )
    except Exception:
        # Not ignorable: the catchment discharge reads this series back, and
        # without it the discharge is silently wrong.
        logger.warning("Failed to persist watershed-mean forcing %s", name, exc_info=True)
        return 0
    return 1


def _persist_family(
    ctx: WorkflowContext,
    sz: SimulationZarr,
    name: str,
    obj: object,
    *,
    store: SimulationStore,
) -> int:
    """Persist one forcing family and return the datasets written."""
    if name == "recharge":
        # The run keeps the recharge it solved, not the one the source holds.
        flow_config = getattr(getattr(ctx, "cfg", None), "flow", None)
        obj = scaled_load_result(obj, recharge_factor_of(flow_config))

    if hasattr(obj, "encoded_codes") and hasattr(obj, "encoded_to_zone"):
        return _persist_geology(sz, obj) + _persist_geology_fractions(ctx, sz, obj)

    if name == "hydrography":
        return _persist_hydrography(ctx, sz, obj, store=store)

    written = 0
    points = getattr(obj, "points", None)
    if points:
        written += _persist_points(sz, name, points)
    fields_list = getattr(obj, "fields", None)
    if fields_list:
        written += _persist_fields(sz, name, fields_list)
    if name in _WATERSHED_MEAN_FORCINGS and fields_list and not points:
        written += _persist_watershed_mean(sz, name, obj, fields_list)
    return written


def step_persist_forcings(ctx: WorkflowContext, *, store: SimulationStore) -> None:
    """Persist input forcings into the Zarr ``forcing/`` group."""
    if ctx.sim_id is None:
        return

    sz = store.open_zarr(ctx.sim_id)
    written = 0

    # getattr, not ctx.setup.soil_forcings: some callers of this step (and a
    # few regression test doubles) hand it a context with no .setup at all.
    soil = getattr(getattr(ctx, "setup", None), "soil_forcings", None)

    try:
        for name, obj in _forcing_sources(ctx, soil):
            if obj is not None:
                written += _persist_family(ctx, sz, name, obj, store=store)

        # Not wrapped like the rest of the loop: a broken soil write is a bug
        # in this feature, not a flaky external source, and must not be
        # swallowed into a silent debug line.
        if soil is not None:
            persist_soil_columns(sz, soil)
    finally:
        sz.close()

    if soil is not None:
        from hydromodpy.model.soil.kernel import annual_budget

        budget = annual_budget(
            soil.years, soil.precipitation, soil.etp, soil.fluxes, soil.columns.basin_weight
        )
        store.write_view(ctx.sim_id, "soil_budget", soil_budget_rows(soil, budget))

    if written:
        logger.debug("Persisted %d forcing datasets for sim %s", written, ctx.sim_id)


def _persist_reference_hydrographic_feature(
    ctx: WorkflowContext,
    hydrography_load_result: object,
    *,
    store: SimulationStore,
) -> bool:
    """Persist the imported hydrography vector as one canonical feature.

    Its permanent part, when the loader wrote one, goes beside it under its own
    feature name, so a run read back later still has both.
    """
    if ctx.sim_id is None:
        return False

    from hydromodpy.spatial.geographic.core.hydrographic_network import (
        HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
        HydrographicNetwork,
    )

    features = getattr(getattr(ctx, "setup", None), "geographic_features", None)
    network = (
        getattr(features, "reference_hydrographic_network", None) if features is not None else None
    )
    if network is None:
        network = HydrographicNetwork.from_hydrography_load_result(hydrography_load_result)
    permanent = (
        getattr(features, "reference_permanent_hydrographic_network", None)
        if features is not None
        else None
    )
    if permanent is None:
        permanent = HydrographicNetwork.permanent_from_hydrography_load_result(
            hydrography_load_result
        )

    written = _persist_network_feature(
        ctx, network, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, store=store
    )
    if written and permanent is not None:
        _persist_network_feature(
            ctx, permanent, HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME, store=store
        )
    return written


def _persist_network_feature(
    ctx: WorkflowContext,
    network: object,
    feature_name: str,
    *,
    store: SimulationStore,
) -> bool:
    """Write one network's vector as the geographic feature *feature_name*."""
    vector_path = getattr(network, "vector_path", None)
    if vector_path in (None, "") or not Path(str(vector_path)).exists():
        return False

    try:
        gdf = network.read_vector()
        if gdf is None or gdf.empty:
            return False
        if gdf.crs is None and getattr(network, "crs", None) not in (None, ""):
            gdf = gdf.set_crs(str(network.crs), allow_override=True)
        store.write_geographic_feature(ctx.sim_id, feature_name, gdf)
        return True
    except Exception:
        # Ignorable: the vector of the reference network is a comparison aid
        # (see _persist_hydrography); the run is complete without it.
        logger.debug("Failed to persist hydrographic network feature %s", feature_name)
        return False


__all__ = (
    "step_persist_forcings",
    "watershed_mean_series",
)
