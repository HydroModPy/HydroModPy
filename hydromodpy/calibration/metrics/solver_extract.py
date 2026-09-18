"""Solver-bridge extractors used by metric extractors.

Resolves the active flow ``SolverAdapter`` from a trial context and pulls
calibration series (point, boundary, cell). Also owns the station-to-cell
mapping helpers that locate observation stations on a structured grid.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.downslope_network import (
    DISTANCE_METHOD,
    seepage_distance_cost,
)
from hydromodpy.calibration.metrics.series import (
    ObservedSeries,
    add_runoff_to_discharge,
    resolve_time_index,
)
from hydromodpy.calibration.observations.network_geometry import geometry_from_run
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    TimeSelector,
)
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_network import build_simulated_network
from hydromodpy.core.units.volumetric_flow import normalize_m3_per_s_unit
from hydromodpy.simulation.planning.plan import RunContext
from hydromodpy.solver.base.registry import get_solver_adapter

logger = get_logger(__name__)

OBSERVED_FAMILIES = {
    "head": "piezometry",
    "discharge": "hydrometry",
    "lake_level": "lake_levels",
}
"""Which loaded data family a calibration variable is observed in."""

RELEASE_FLUX_UNIT = "m3/s"
"""The one unit the network criterion can threshold a release field in."""


if TYPE_CHECKING:
    from hydromodpy.calibration.config import (
        CalibOutputDecl,
        CalibOutputNetwork,
        CalibOutputPoint,
    )


def resolve_flow_adapter(trial_ctx: Any) -> tuple[Any, RunContext] | None:
    """Return ``(adapter, run_ctx)`` for the active flow run, or ``None``.

    A calibration trial runs exactly one flow process by design. This helper
    returns the first such ``ProcessRun`` it finds along with a freshly
    instantiated ``SolverAdapter`` and a ``RunContext`` whose ``state`` is the
    trial context itself.
    """
    registry_state = getattr(trial_ctx, "execution", None)
    if registry_state is None:
        return None
    models = registry_state.models_by_run_id or {}
    if not models:
        return None
    plan = getattr(registry_state, "simulation_plan", None)
    if plan is None:
        return None

    flow_run = None
    for run in plan.runs:
        if run.process_type == "flow" and run.id in models:
            flow_run = run
            break
    if flow_run is None:
        return None
    try:
        adapter = get_solver_adapter(flow_run.process_type, flow_run.solver)
    except KeyError:
        return None
    run_ctx = RunContext.of(trial_ctx, plan=plan, run=flow_run)
    return adapter, run_ctx


def slice_time(values: np.ndarray, time: Any, reducer: str) -> list[float]:
    """Apply ``time`` selector and ``reducer`` to a 1D array of simulated values."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        return []
    if time == "first":
        arr = arr[:1]
    elif time == "last":
        arr = arr[-1:]
    if reducer == "mean":
        return [float(np.nanmean(arr))]
    if reducer == "sum":
        return [float(np.nansum(arr))]
    if reducer == "last":
        return [float(arr[-1])]
    return [float(v) for v in arr]


def _coerce_length_to_m(value: Any) -> float | None:
    """Pull the magnitude in metres from a pint Quantity or bare number."""
    if value is None:
        return None
    to_m = getattr(value, "to", None)
    if callable(to_m):
        try:
            return float(value.to("m").magnitude)
        except Exception:
            pass
    return float(value)


def point_xy_from_output(output: CalibOutputPoint) -> tuple[float, float] | None:
    """Return planar point coordinates from an output declaration."""
    x_m = _coerce_length_to_m(output.x)
    y_m = _coerce_length_to_m(output.y)
    if x_m is not None and y_m is not None:
        return x_m, y_m
    geometry = output.geometry
    if not geometry:
        return None
    if str(geometry.get("type", "")).lower() != "point":
        raise ValueError("Point calibration geometry must be a GeoJSON Point")
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        raise ValueError("Point calibration geometry requires two coordinates")
    return float(coords[0]), float(coords[1])


def observable_series(result: ObservableResult, *, name: str) -> pd.Series:
    """Rebuild a pandas series from an observable, for the scoring helpers.

    ``score`` aligns on a time index, so an observable that carries one keeps
    it; one that does not falls back to a positional index, exactly as the
    binary readers did before.
    """
    values = np.asarray(result.values, dtype=float).reshape(-1)
    if result.times is not None and len(result.times) == values.size:
        return pd.Series(values, index=result.times, name=name)
    return pd.Series(values, name=name)


def _request_times(time: Any) -> TimeSelector:
    """Map an output declaration's time selector onto the observable contract.

    A declaration may also carry a list of dates, which the reducer handles
    downstream; the adapter is then asked for the whole run.
    """
    return time if time in ("all", "first", "last") else "all"


def observable_request_for_output(
    name: str,
    output: CalibOutputDecl,
    ctx: Any,
) -> ObservableRequest:
    """Translate one calibration output declaration into an observable request.

    This is the single place where the calibration vocabulary meets the solver
    one. An unknown support raises here instead of silently falling through to
    a cell request, which is what used to happen.
    """
    times = _request_times(output.time)
    support = output.support
    if support == "point":
        station = getattr(output, "observes", None)
        if station is not None:
            cell = cell_for_station(ctx, str(station), variable=str(output.variable))
            if cell is None:
                raise NotImplementedError(
                    f"Output {name!r} is scored against station {station!r}, whose cell "
                    "the project could not resolve. A named station is located by its own "
                    "record, not by the coordinates written here, so that this output and "
                    "the single-metric route read the same cell."
                )
        else:
            xy = point_xy_from_output(output)
            if xy is None:
                raise ValueError(f"Point calibration output {name!r} requires x/y or geometry")
            cell = find_cell_at_point(ctx, xy[0], xy[1])
        if cell is None:
            raise NotImplementedError(
                f"Could not map point calibration output {name!r} to a solver cell"
            )
        # The declared variable is honoured. Coercing it to a head meant a block
        # asking for the discharge at a gauge was silently scored on a head, and a
        # gauge is the commonest calibration target there is. A backend that cannot
        # serve the named variable at a cell refuses it by name.
        return ObservableRequest(
            id=name,
            name=str(output.variable),
            support="cell",
            cell=cell,
            times=times,
        )
    if support == "boundary":
        return ObservableRequest(
            id=name,
            name="discharge",
            support="boundary",
            key=str(output.boundary_id),
            times=times,
        )
    if support == "lake":
        return ObservableRequest(
            id=name,
            name=str(output.variable),
            support="lake",
            key=str(output.lake_id),
            times=times,
        )
    if support == "network":
        # The whole per-cell release field, read at the declared timesteps. The
        # backend decides which of its packages count as a resurgence; this
        # layer never names one.
        return ObservableRequest(id=name, name=str(output.variable), support="cells", times=times)
    if support == "cell":
        if output.row is None or output.col is None:
            raise NotImplementedError(
                f"Cell calibration output {name!r} needs row and col: a flat cell_id "
                "selector is not exposed by any solver."
            )
        return ObservableRequest(
            id=name,
            name=str(output.variable),
            support="cell",
            cell=(int(output.layer), int(output.row), int(output.col)),
            times=times,
        )
    raise ValueError(f"Unknown calibration output support {support!r} on output {name!r}")


def require_release_flux_unit(units: str, *, name: str) -> None:
    """Refuse a release field the criterion would threshold in the wrong unit.

    The seepage threshold is a recharge in m/s times a cell area, so it is a
    volumetric flow in m3/s and the field it is compared to has to be one too.
    Adapters spell that unit the CF way (``m3 s-1``) and the catalog the solidus
    way (``m3/s``); the space becomes a product so both reach the one
    volumetric-flow vocabulary the repository keeps.
    """
    try:
        canonical = normalize_m3_per_s_unit(units)
    except ValueError as exc:
        raise ObjectiveError(
            f"Output {name!r}: the solver served the release field in {units!r}, a token the "
            "volumetric-flow vocabulary does not hold, so the criterion cannot tell whether "
            f"it is the {RELEASE_FLUX_UNIT} it thresholds in. ({exc})"
        ) from exc
    if canonical != RELEASE_FLUX_UNIT:
        raise ObjectiveError(
            f"Output {name!r}: the solver served the release field in {units!r}, that is "
            f"{canonical}, and the criterion thresholds in {RELEASE_FLUX_UNIT}. The two "
            "sides differ by a constant factor, so the simulated network would follow the "
            "unit rather than the hydrogeology."
        )


def score_network_output(
    run_ctx: RunContext,
    name: str,
    output: CalibOutputNetwork,
    result: ObservableResult,
) -> tuple[list[float], dict[str, float]]:
    """Turn one per-cell release field into the pair ``(D_so, D_os)``.

    The pair is what a block scores; every other number the criterion produces
    travels beside it as a diagnostic, which is how a session records thirty
    quantities per trial without promoting a single run.

    The static geometry is rebuilt here at every trial. It is one graph build
    and three ``O(n_cells)`` passes, measured under a second on a seven
    thousand cell mesh, which is nothing beside one solve; hoisting it would
    mean caching mesh identity across forked trial contexts for no measurable
    gain.
    """
    require_release_flux_unit(result.units, name=name)
    geometry, observed_network = geometry_from_run(run_ctx, output)
    simulated = build_simulated_network(
        result.values,
        threshold_m3_s=geometry.threshold_m3_s,
        metric=geometry.metric,
    )
    scored = seepage_distance_cost(
        simulated=simulated,
        observed=geometry.observed,
        outlet=geometry.outlet,
        catchment=geometry.catchment,
        metric=geometry.metric,
        distance_to_observed=geometry.distance_to_observed,
        distance_to_observed_raw=geometry.distance_to_observed_raw,
        cell_area_m2=geometry.cell_area_m2,
        length_scale_m=geometry.length_scale_m,
        saturation_cap_m=geometry.saturation_cap_m,
        excluded=geometry.excluded,
        weighting=output.weighting,
        max_unreachable_fraction=float(output.max_unreachable_fraction),
        roptim_max=float(output.roptim_max),
    )
    if scored.status == "failed":
        raise ObjectiveError(
            f"Output {name!r}: frac_unreachable_so = "
            f"{scored.components.get('frac_unreachable_so', float('nan')):.1%} of the simulated "
            "network never reaches the mapped one, over the "
            f"{output.max_unreachable_fraction:.0%} bound. That target is fixed for the whole "
            "search, so the trial cannot have shrunk it: the routing surface still holds "
            "depressions, and averaging D_so over a support truncated by them is a fiction, "
            "the cells dropped being never a random sample. Condition the surface, or raise "
            "max_unreachable_fraction knowing what it buys. The reciprocal diagnostic, "
            "frac_unreachable_os = "
            f"{scored.components.get('frac_unreachable_os', float('nan')):.1%}, is reported and "
            "not bounded: it descends onto the simulated network, which the search itself "
            "retracts at the high end of its bracket."
        )

    roptim = scored.components["roptim"]
    if np.isfinite(roptim) and roptim > float(output.roptim_max):
        message = (
            f"Output {name!r}: roptim = {roptim:.2f} exceeds the validity bound "
            f"{output.roptim_max:.2f}. The agreement between the two networks is coarser "
            "than the mesh, which qualifies the result; it does not say the calibrated "
            "value is wrong."
        )
        if output.on_roptim_violation == "error":
            raise ObjectiveError(message)
        logger.warning(message)

    logger.info("Output %s scored with distance method %s.", name, DISTANCE_METHOD)

    # The output of this criterion is the pair (D_so, D_os), two distances in
    # metres, and not a series. D_so has no support when the network is empty,
    # so it is rebuilt from D_os and the signed residual rather than read: that
    # way the pair and the residual the bracket closes on cannot disagree.
    d_os = float(scored.components["D_os"])
    pair = [d_os + scored.signed_gap, d_os]
    # Travel beside alpha_obs_closure: what qualifies the geometry the trial
    # was scored against, not the trial itself.
    network_provenance = {
        "observed_network_clipped": 1.0 if observed_network.clipped else 0.0,
        "observed_network_is_dem_derived": 1.0 if observed_network.dem_derived else 0.0,
    }
    diagnostics = {
        f"{name}.{key}": float(value)
        for key, value in {
            **scored.components,
            **geometry.diagnostics,
            **network_provenance,
        }.items()
    }
    return pair, diagnostics


@dataclass(frozen=True)
class ExtractedOutputs:
    """What one batch of output extraction produced.

    ``values`` holds the scored vector of every output, after its time selector
    and reducer. ``series`` holds the same values still carrying their
    timestamps, for the outputs the run could date; an output scored against a
    loaded record needs those to align on, and one that reduces to a scalar has
    none. ``diagnostics`` carries what the network criterion emits beside its
    cost.
    """

    values: dict[str, list[float]]
    series: dict[str, pd.Series]
    diagnostics: dict[str, float]


def extract_outputs(ctx: Any, outputs: Mapping[str, CalibOutputDecl]) -> ExtractedOutputs:
    """Ask the flow adapter for every declared output, in one batch.

    One adapter resolution and one call per trial, whatever the number of
    outputs, so a backend opens each binary file once. Translation errors are
    reported per output because they name a declaration the user wrote; the
    extraction itself is a single operation and fails as one.

    Returns the scored values per output and, beside them, the diagnostics the
    network criterion produces, which the caller merges into the components of
    the trial.
    """
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for calibration extraction")
    adapter, run_ctx = resolved

    requests: list[ObservableRequest] = []
    gauge_comparable: dict[str, str] = {}
    for name, output in outputs.items():
        try:
            request = observable_request_for_output(name, output, ctx)
        except Exception as exc:
            raise RuntimeError(
                f"Output {name!r} extraction failed: {type(exc).__name__}: {exc}"
            ) from exc
        requests.append(request)
        if _is_a_gauge_comparable_discharge(output, request):
            # A gauge measures the whole streamflow; a drain budget is baseflow
            # alone. The runoff forcing is what makes the two comparable, scaled
            # by the area this cell drains, exactly as the single-metric route
            # does it. Without this the two routes score different quantities.
            area_id = f"_area:{name}"
            gauge_comparable[name] = area_id
            requests.append(
                ObservableRequest(
                    id=area_id,
                    name="upstream_area",
                    support="cell",
                    cell=request.cell,
                    diagonal_neighbors=request.diagonal_neighbors,
                )
            )

    # The time grid is passed so a dated output comes back dated. An output
    # scored against a loaded record has to align on those timestamps, and the
    # ones scored positionally read the values and ignore the index.
    results = adapter.extract_observables(
        run_ctx, None, requests, time_index=resolve_time_index(ctx, n_timesteps=0)
    )

    simulated: dict[str, list[float]] = {}
    series: dict[str, pd.Series] = {}
    diagnostics: dict[str, float] = {}
    for name, output in outputs.items():
        result = results.get(name)
        if result is None or np.asarray(result.values).size == 0:
            raise NotImplementedError(f"Solver returned no calibration values for output {name!r}")
        if output.support == "network":
            simulated[name], scored = score_network_output(run_ctx, name, output, result)
            diagnostics.update(scored)
            continue
        values = result.values
        dated = _dated_series(result)
        if name in gauge_comparable and not getattr(result, "includes_runoff", False):
            if dated is None:
                raise NotImplementedError(
                    f"Output {name!r} scores a gauge record on the simulated discharge, "
                    "which needs the runoff forcing added on a time axis, and the solver "
                    "returned the values without one."
                )
            area = float(
                np.asarray(results[gauge_comparable[name]].values, dtype=float).reshape(-1)[0]
            )
            fraction = report_the_area_a_gauge_drains(
                str(getattr(output, "observes", "?")), ctx, area_m2=area, where=name
            )
            if fraction is not None:
                diagnostics[f"{name}.drained_fraction"] = fraction
            dated = add_runoff_to_discharge(dated, ctx, area_m2=area)
            values = dated.to_numpy()
        simulated[name] = slice_time(values, output.time, output.reducer)
        if dated is not None:
            series[name] = dated
    return ExtractedOutputs(values=simulated, series=series, diagnostics=diagnostics)


def report_the_area_a_gauge_drains(
    station: str, ctx: Any, *, area_m2: float, where: str | None = None
) -> float | None:
    """State what share of the delineated catchment this gauge's cell drains.

    A gauge coordinate is not on the flow path the DEM produced, and the
    delineation says so for the outlet: it reports the distance its snap moved
    the point. Nothing said it for a gauge, so a station landing two cells off
    the talweg was scored on a fraction of the basin with no trace. There is no
    universal threshold to veto on, so the number is stated on every run and
    published beside the cost, the way the catchment coverage already is.
    """
    geo = getattr(getattr(ctx, "setup", None), "geographic", None)
    catchment_km2 = float(getattr(geo, "catch_area", 0.0) or 0.0)
    if catchment_km2 <= 0.0 or area_m2 <= 0.0:
        return None
    fraction = (area_m2 / 1e6) / catchment_km2
    logger.info(
        "Gauge %s%s sits on a cell draining %.3f km2, %.1f%% of the %.3f km2 delineated "
        "catchment. A share far from the one the gauge really commands means the station did "
        "not land on the routed talweg.",
        station,
        f" (output {where!r})" if where else "",
        area_m2 / 1e6,
        100.0 * fraction,
        catchment_km2,
    )
    return fraction


def _is_a_gauge_comparable_discharge(output: Any, request: ObservableRequest) -> bool:
    """Tell whether this output is a discharge that a gauge record will be fitted to.

    Only then is the runoff term owed. A boundary's flux is that boundary's flux,
    and an output scored on a vector typed into the file is not being compared to
    what a gauge measures.
    """
    return (
        request.name == "discharge"
        and request.support == "cell"
        and getattr(output, "observes", None) is not None
    )


def _dated_series(result: Any) -> pd.Series | None:
    """Return the result as a timestamped series, or ``None`` when it is not one."""
    times = getattr(result, "times", None)
    if times is None:
        return None
    values = np.asarray(result.values, dtype=float).ravel()
    index = pd.DatetimeIndex(times)
    if values.size == 0 or len(index) != values.size:
        return None
    return pd.Series(values, index=index)


# ---------------------------------------------------------------------------
# Station-to-cell mapping
# ---------------------------------------------------------------------------


def resolve_station_cells(
    ctx: Any,
    observed: list[ObservedSeries],
    *,
    variable: str = "head",
) -> dict[str, tuple[int, int, int]]:
    """Resolve station ids to structured ``(layer, row, col)`` cells.

    ``variable`` names the data family the stations come from: piezometry for a
    head calibration, hydrometry for a discharge one. A gauge needs its cell for
    the same reason a piezometer does, and it is the same lookup.
    """
    records = getattr(ctx.loaded_data, OBSERVED_FAMILIES.get(variable, variable), None)
    if records is None:
        return {}
    cells: dict[str, tuple[int, int, int]] = {}
    for obs_rec in observed:
        cell = _cell_of_one_station(ctx, records, obs_rec.station_id, variable=variable)
        if cell is not None:
            cells[obs_rec.station_id] = cell
    return cells


def cell_for_station(ctx: Any, station_id: str, *, variable: str) -> tuple[int, int, int] | None:
    """Resolve one station to its cell, by the one lookup every route uses.

    A gauge coordinate is never exactly on the cell the model routes through:
    the record carries the position the loader already reconciled with the mesh,
    and a coordinate retyped in a configuration does not. Two routes scoring the
    same station have to ask the solver about the same cell, or their costs are
    not comparable, which is measurable and was measured.
    """
    records = getattr(ctx.loaded_data, OBSERVED_FAMILIES.get(variable, variable), None)
    if records is None:
        return None
    return _cell_of_one_station(ctx, records, str(station_id), variable=variable)


def _cell_of_one_station(
    ctx: Any, records: Any, station_id: str, *, variable: str = "head"
) -> tuple[int, int, int] | None:
    for rec in getattr(records, "points", None) or []:
        if str(rec.station_id) != station_id:
            continue
        cell_ij = getattr(rec, "cell_ij", None)
        cell = (
            _coerce_cell_ij(cell_ij)
            if cell_ij is not None
            else _coerce_structured_cell(
                getattr(rec, "cell", None) or getattr(rec, "station_cell", None)
            )
        )
        if cell is None and _a_coordinate_locates_this_variable(variable):
            xy = _xy_from_record(rec)
            if xy is not None:
                cell = find_cell_at_point(ctx, xy[0], xy[1])
        return cell
    return None


def _a_coordinate_locates_this_variable(variable: str) -> bool:
    """Tell whether a coordinate is enough to say which cell a variable is read at.

    A head is read at the cell the point falls in, and nothing upstream enters it.
    A discharge is not: it is the flow accumulated over everything that drains to
    that cell, so the cell has to be the one the routing actually passes through.
    Measured on Nancon at the basin outlet, both the gauge's own coordinate and
    the snapped outlet resolve to cells the solver reports as draining 0.107 and
    0.022 km2 of a 64.631 km2 catchment, two tenths and three hundredths of a per
    cent. Until that is reconciled, a discharge station is not located by its
    coordinate and the catchment total is used, which is the quantity an outlet
    gauge measures and what this route has always returned.
    """
    return str(variable) != "discharge"


def _coerce_cell_ij(value: Any) -> tuple[int, int, int] | None:
    """Return ``(layer, row, col)`` from ``(row, col[, layer])`` metadata."""
    try:
        parts = tuple(value)
    except TypeError:
        return None
    if len(parts) == 2:
        return (0, int(parts[0]), int(parts[1]))
    if len(parts) >= 3:
        return (int(parts[2]), int(parts[0]), int(parts[1]))
    return None


def _coerce_structured_cell(value: Any) -> tuple[int, int, int] | None:
    """Return ``(layer, row, col)`` from common station metadata shapes."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        layer = value.get("layer", value.get("k", 0))
        row = value.get("row", value.get("i"))
        col = value.get("col", value.get("j"))
        if row is None or col is None:
            return None
        return (int(layer), int(row), int(col))
    try:
        parts = tuple(value)
    except TypeError:
        return None
    if len(parts) == 2:
        return (0, int(parts[0]), int(parts[1]))
    if len(parts) >= 3:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    return None


def _xy_from_record(record: Any) -> tuple[float, float] | None:
    """Extract planar x/y coordinates from an observation record.

    ``PointRecord.location`` is where every loader puts the station's position,
    and it was the one place this function did not look. The consequence was
    silent and large: no station ever resolved to a cell, so a gauge was scored
    on the whole-catchment discharge whatever its position, which is right only
    for a gauge at the outlet.
    """
    location = getattr(record, "location", None)
    if location is not None:
        x_val = getattr(location, "x", None)
        y_val = getattr(location, "y", None)
        if x_val is not None and y_val is not None:
            return float(x_val), float(y_val)
    for x_name, y_name in (("x", "y"), ("easting", "northing"), ("longitude", "latitude")):
        x_val = getattr(record, x_name, None)
        y_val = getattr(record, y_name, None)
        if x_val is not None and y_val is not None:
            return float(x_val), float(y_val)
    geometry = getattr(record, "geometry", None)
    x_val = getattr(geometry, "x", None)
    y_val = getattr(geometry, "y", None)
    if x_val is not None and y_val is not None:
        return float(x_val), float(y_val)
    return None


def find_cell_at_point(ctx: Any, x: float, y: float) -> tuple[int, int, int] | None:
    """Return the cell selector nearest to ``(x, y)``, or ``None``.

    The backend answers. It is the only party that knows the grid it wrote:
    structured rows and columns, a Voronoi cell list, or a flopy model grid.
    Asking it, rather than reading one backend's internals here, is what lets
    this path serve a solver added tomorrow.
    """
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        return None
    adapter, run_ctx = resolved
    locate = getattr(adapter, "locate_cell", None)
    if locate is None:
        return None
    return locate(run_ctx, x, y)


__all__ = [
    "ExtractedOutputs",
    "extract_outputs",
    "score_network_output",
    "find_cell_at_point",
    "observable_request_for_output",
    "report_the_area_a_gauge_drains",
    "observable_series",
    "point_xy_from_output",
    "require_release_flux_unit",
    "resolve_flow_adapter",
    "resolve_station_cells",
    "slice_time",
]
