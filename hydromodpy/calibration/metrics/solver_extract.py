"""Solver-bridge extractors used by metric extractors.

Resolves the active flow ``SolverAdapter`` from a trial context and pulls
calibration series (point, boundary, cell). Also owns the station-to-cell
mapping helpers that locate observation stations on a structured grid.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.downslope_network import (
    DISTANCE_METHOD,
    seepage_distance_cost,
)
from hydromodpy.calibration.metrics.gauge_snap import GaugeSnapError, snap_to_most_accumulated
from hydromodpy.calibration.metrics.observable_scoring import (
    dated_series,
    select_observable_times,
    slice_time,
)
from hydromodpy.calibration.metrics.series import (
    ObservedSeries,
    add_runoff_to_discharge,
    resolve_time_index,
)
from hydromodpy.calibration.observations.network_geometry import (
    aquifer_extent,
    geometry_from_run,
    mesh_cell_m,
)
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    TimeSelector,
)
from hydromodpy.core.exceptions import ObjectiveError, ObservableNotAvailableError
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
    snap_m = _snap_radius_m(output)
    if support == "point":
        station = getattr(output, "observes", None)
        snap_xy: tuple[float, float] | None = None
        if station is not None:
            cell = cell_for_station(ctx, str(station), variable=str(output.variable))
            if snap_m is not None:
                # The snap is what makes a discharge station's coordinate usable,
                # so the gate that keeps it out by default opens here, and only
                # here. The record's own position comes first, for the same
                # reason a named station is never located by the x/y written
                # beside it.
                snap_xy = station_xy(ctx, str(station), variable=str(output.variable))
                if snap_xy is None:
                    snap_xy = point_xy_from_output(output)
                if cell is None and snap_xy is not None:
                    cell = find_cell_at_point(ctx, snap_xy[0], snap_xy[1])
                if cell is None:
                    raise NotImplementedError(
                        f"Output {name!r} asks to snap station {station!r} with "
                        f"snap_radius = {snap_m:g} m, and no cell could be resolved to "
                        "snap from: neither the loader nor the solver placed it."
                    )
            if cell is None and str(output.variable) == "discharge":
                # The same fallback the single-metric route takes, and for the
                # same reason: a discharge station is deliberately not placed by
                # its coordinate, so a project whose loader resolved no cell for
                # it has the whole-catchment series and nothing else. That series
                # is what an outlet gauge measures. Refusing here instead would
                # leave the weighted-block route unable to score a gauge on any
                # project the single-metric route scores fine, which is the
                # opposite of the comparability this lookup exists for.
                logger.info(
                    "Output %s scores station %s on the whole-catchment discharge: no cell "
                    "was resolved for it, which is right for the outlet gauge and says so "
                    "for the others.",
                    name,
                    station,
                )
                return ObservableRequest(id=name, name="discharge", support="domain", times=times)
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
            snap_xy = xy
        if cell is None:
            raise NotImplementedError(
                f"Could not map point calibration output {name!r} to a solver cell"
            )
        if snap_m is not None:
            cell = snap_gauge_cell(
                ctx,
                name,
                cell,
                xy=snap_xy,
                radius_m=snap_m,
                diagonal_neighbors=output.diagonal_neighbors,
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
            diagonal_neighbors=output.diagonal_neighbors,
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
        cell = (int(output.layer), int(output.row), int(output.col))
        if snap_m is not None:
            cell = snap_gauge_cell(
                ctx,
                name,
                cell,
                xy=None,
                radius_m=snap_m,
                diagonal_neighbors=output.diagonal_neighbors,
            )
        return ObservableRequest(
            id=name,
            name=str(output.variable),
            support="cell",
            cell=cell,
            times=times,
            diagonal_neighbors=output.diagonal_neighbors,
        )
    raise ValueError(f"Unknown calibration output support {support!r} on output {name!r}")


def _snap_radius_m(output: Any) -> float | None:
    """Return the opt-in gauge snap radius in metres, or None when it is off."""
    return _coerce_length_to_m(getattr(output, "snap_radius", None))


def snap_gauge_cell(
    ctx: Any,
    name: str,
    cell: tuple[int, int, int],
    *,
    xy: tuple[float, float] | None,
    radius_m: float,
    diagonal_neighbors: bool = False,
) -> tuple[int, int, int]:
    """Move a gauge's cell onto the most accumulated cell within ``radius_m``.

    The drained area is asked of the solver, over the whole mesh, on the graph
    its discharge is routed on: snapping on any other surface would land the
    gauge on a talweg the model does not route. ``xy`` is the gauge coordinate
    the radius is measured from; ``None`` measures it from the cell centre,
    which is all a ``support = "cell"`` output declares.
    """
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError(
            f"Output {name!r} asks for a gauge snap and no flow solver adapter is available."
        )
    adapter, run_ctx = resolved
    area_id = f"_snap:{name}"
    xy_id = f"_snap_xy:{name}"
    here_id = f"_snap_here:{name}"
    try:
        results = adapter.extract_observables(
            run_ctx,
            None,
            [
                ObservableRequest(
                    id=area_id,
                    name="upstream_area",
                    support="cells",
                    diagonal_neighbors=bool(diagonal_neighbors),
                ),
                ObservableRequest(id=xy_id, name="cell_xy", support="cells"),
                ObservableRequest(id=here_id, name="cell_xy", support="cell", cell=cell),
            ],
        )
        accumulation = np.asarray(results[area_id].values, dtype=float).reshape(-1)
        centroids = np.asarray(results[xy_id].values, dtype=float).reshape(-1, 2)
        here = np.asarray(results[here_id].values, dtype=float).reshape(2)
    except (KeyError, ObservableNotAvailableError) as exc:
        raise NotImplementedError(
            f"Output {name!r} asks for a gauge snap, and the solver of run {run_ctx.run.id!r} "
            "serves no drained area or cell centres to search."
        ) from exc
    start = int(np.argmin(np.hypot(centroids[:, 0] - here[0], centroids[:, 1] - here[1])))
    x, y = xy if xy is not None else (float(here[0]), float(here[1]))
    try:
        snap = snap_to_most_accumulated(
            centroids, accumulation, x=x, y=y, radius_m=radius_m, start_index=start
        )
    except GaugeSnapError as exc:
        raise GaugeSnapError(f"Output {name!r}: {exc}") from exc

    if not snap.moved:
        logger.info(
            "Output %s: the gauge already sits on the most accumulated cell within %g m, "
            "%s, draining %.3f km2. Not moved.",
            name,
            radius_m,
            cell,
            snap.area_before_m2 / 1e6,
        )
        return cell
    target = centroids[snap.index_after]
    located = adapter.locate_cell(run_ctx, float(target[0]), float(target[1]))
    snapped = (int(cell[0]), int(located[1]), int(located[2])) if located else None
    check = None
    if snapped is not None:
        check_id = f"_snap_check:{name}"
        check = adapter.extract_observables(
            run_ctx,
            None,
            [ObservableRequest(id=check_id, name="cell_xy", support="cell", cell=snapped)],
        )[check_id].values
    if check is None or not np.allclose(np.asarray(check, dtype=float).reshape(2), target):
        raise NotImplementedError(
            f"Output {name!r}: the solver did not locate the snapped cell {snap.index_after} "
            f"at its own centre (got {located}), so the snap cannot be addressed."
        )
    logger.info(
        "Output %s: gauge snapped %.1f m (of %g m allowed) onto the most accumulated cell, "
        "from %s draining %.3f km2 to %s draining %.3f km2. The output is scored at the "
        "snapped cell.",
        name,
        snap.distance_m,
        radius_m,
        cell,
        snap.area_before_m2 / 1e6,
        snapped,
        snap.area_after_m2 / 1e6,
    )
    return snapped


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


def _last_state(values: Any) -> np.ndarray:
    """Return the last timestep of a per-cell field, as the network reads it."""
    field = np.asarray(values, dtype=float)
    return field[-1, :] if field.ndim == 2 else field.reshape(-1)


def _area_mean(values: np.ndarray, cells: np.ndarray, areas: np.ndarray) -> float:
    """Area-weighted mean of ``values`` over ``cells``, finite values only."""
    kept = cells & np.isfinite(values) & np.isfinite(areas)
    weight = float(areas[kept].sum())
    return float((values[kept] * areas[kept]).sum() / weight) if weight > 0.0 else float("nan")


def catchment_saturation(
    run_ctx: RunContext,
    geometry: Any,
    saturated_thickness: ObservableResult | None,
) -> dict[str, float]:
    """Return ``d_sat_m``, ``d_aquifer_m`` and their ratio over the catchment.

    ``d_sat_m`` is the paper's ``dsat``: the saturated thickness the model
    computes, averaged by area over the catchment, at the state the network is
    read from. It turns ``K/R`` into ``T/R``. ``d_aquifer_m`` is the imposed
    thickness over the same cells. ``T/R`` stops being independent of it when
    the aquifer runs nearly full, so the ratio is published beside it.

    A cell with no finite thickness is left out of ``d_sat_m``, and the share
    of catchment area left out is published. MODFLOW writes one sentinel for a
    dry cell (HDRY) and another for a cell it never computed (HNOFLO), and the
    extractor maps both to NaN, so the thickness alone cannot tell them apart.
    The mesh can: its inactive mask is what became IDOMAIN = 0. When it has
    one, the share splits into ``d_sat_dry_fraction`` (active, no water table:
    a physical state that biases ``d_sat_m`` upward) and
    ``d_sat_inactive_fraction`` (outside the solved domain, a lake footprint
    for one: a modelling choice, not a state). A mesh without the mask keeps
    the single ``d_sat_unset_fraction``.

    Empty when the backend serves no saturated thickness, and when it serves
    one on another cell count: these values never enter the scored pair, so a
    mismatch warns and leaves the trial scored.
    """
    if saturated_thickness is None:
        return {}
    cells = np.asarray(geometry.catchment, dtype=bool).reshape(-1)
    areas = np.asarray(geometry.cell_area_m2, dtype=float).reshape(-1)
    thickness = _last_state(saturated_thickness.values)
    if thickness.size != cells.size:
        logger.warning(
            "No d_sat_m: the saturated thickness holds %d cells, the mesh holds %d.",
            thickness.size,
            cells.size,
        )
        return {}
    d_sat = _area_mean(thickness, cells, areas)
    unset = cells & ~np.isfinite(thickness)
    catchment_area = float(areas[cells].sum())

    def share(selected: np.ndarray) -> float:
        return float(areas[selected].sum() / catchment_area) if catchment_area > 0.0 else np.nan

    out = {"d_sat_m": d_sat}
    imposed, inactive = aquifer_extent(run_ctx, cells.size)
    if inactive is None:
        out["d_sat_unset_fraction"] = share(unset)
    else:
        out["d_sat_dry_fraction"] = share(unset & ~inactive)
        out["d_sat_inactive_fraction"] = share(unset & inactive)
    if imposed is not None:
        d_aquifer = _area_mean(imposed, cells, areas)
        out["d_aquifer_m"] = d_aquifer
        out["d_sat_over_d"] = d_sat / d_aquifer if d_aquifer > 0.0 else float("nan")
    return out


def score_network_output(
    run_ctx: RunContext,
    name: str,
    output: CalibOutputNetwork,
    result: ObservableResult,
    *,
    saturated_thickness: ObservableResult | None = None,
) -> tuple[list[float], dict[str, float]]:
    """Turn one per-cell release field into the pair ``(D_so, D_os)``.

    The pair is what a block scores; every other number the criterion produces
    travels beside it as a diagnostic, which is how a session records thirty
    quantities per trial without promoting a single run.

    ``saturated_thickness`` is the per-cell field of the same run. It feeds
    :func:`catchment_saturation` only and never enters the pair.

    The static geometry is rebuilt here at every trial. It is one graph build
    and three ``O(n_cells)`` passes, measured under a second on a seven
    thousand cell mesh, which is nothing beside one solve; hoisting it would
    mean caching mesh identity across forked trial contexts for no measurable
    gain.
    """
    require_release_flux_unit(result.units, name=name)
    geometry, observed_network, projection = geometry_from_run(run_ctx, output)
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

    # Eq. 4 is not read here. The paper reads it at the optimum, and a search
    # crosses trials far from it on the way: testing every trial warned on
    # most of them and, in strict mode, refused a whole bracket before it
    # closed. The runner reads roptim once, on the trial it returns.

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
        # What the output's observed_rasterization drew: every cell the map
        # holds on the mesh, and the reaches kept at their midpoint cell.
        "n_observed_cells": float(int(projection.mask.sum())),
        "n_observed_features_fallback": float(projection.n_fallback_parts),
    }
    diagnostics = {
        f"{name}.{key}": float(value)
        for key, value in {
            **scored.components,
            **geometry.diagnostics,
            **network_provenance,
            **catchment_saturation(run_ctx, geometry, saturated_thickness),
            # One cell of the mesh scored here, the default width of the interval
            # a search on this criterion reports. Measured with the geometry, so
            # the runner reads it off the trial and asks the mesh nothing.
            "cell_spacing_m": mesh_cell_m(run_ctx, geometry),
        }.items()
    }
    return pair, diagnostics


@dataclass(frozen=True)
class ExtractedOutputs:
    """What one batch of output extraction produced.

    ``observables`` retains series with their units after runoff correction.
    Network fields are represented only by their prepared distances below.
    ``values`` holds the scored vector of every output, after its time selector
    and reducer. ``series`` holds the same values still carrying their
    timestamps, for the outputs the run could date; an output scored against a
    loaded record needs those to align on, and one that reduces to a scalar has
    none. ``diagnostics`` carries what the network criterion emits beside its
    cost.
    """

    observables: dict[str, ObservableResult]
    values: dict[str, list[float]]
    series: dict[str, pd.Series]
    diagnostics: dict[str, float]


def _saturated_thickness_or_none(
    adapter: Any,
    run_ctx: RunContext,
    name: str,
    output: CalibOutputNetwork,
    time_index: Any,
) -> ObservableResult | None:
    """Ask for the saturated thickness beside a network output, or None.

    A call of its own: a backend that serves no such field loses ``d_sat_m``
    and keeps the criterion.
    """
    request = ObservableRequest(
        id=f"_saturated_thickness:{name}",
        name="saturated_thickness",
        support="cells",
        times=_request_times(output.time),
    )
    try:
        served = adapter.extract_observables(run_ctx, None, [request], time_index=time_index)
    except ObservableNotAvailableError as exc:
        logger.info("Output %s: no saturated thickness from this backend (%s).", name, exc)
        return None
    return served.get(request.id)


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
    # The area request a gauge output owes its runoff scaling, or None when the
    # output is the whole-catchment series, whose runoff is the basin's own.
    gauge_comparable: dict[str, str | None] = {}
    snapped_onto: dict[tuple[int, int, int], list[str]] = {}
    for name, output in outputs.items():
        try:
            request = observable_request_for_output(name, output, ctx)
        except Exception as exc:
            raise RuntimeError(
                f"Output {name!r} extraction failed: {type(exc).__name__}: {exc}"
            ) from exc
        requests.append(request)
        if request.cell is not None and _snap_radius_m(output) is not None:
            snapped_onto.setdefault(tuple(request.cell), []).append(name)
        if _is_a_gauge_comparable_discharge(output, request):
            # A gauge measures the whole streamflow; a drain budget is baseflow
            # alone. The runoff forcing is what makes the two comparable, scaled
            # by the area this cell drains, exactly as the single-metric route
            # does it. Without this the two routes score different quantities.
            if request.support != "cell":
                # The catchment series drains the whole basin, and the forcing
                # is already areal over it: there is no upstream area to ask for.
                gauge_comparable[name] = None
                continue
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

    for cell, names in snapped_onto.items():
        if len(names) > 1:
            # Two gauges on one reach within each other's radius: both would be
            # scored on the same simulated series, which no weighting can undo.
            logger.warning(
                "Outputs %s were all snapped onto cell %s, so they score one simulated "
                "discharge against %d records. Shrink the snap_radius of the upstream one.",
                ", ".join(sorted(names)),
                cell,
                len(names),
            )

    # The time grid is passed so a dated output comes back dated. An output
    # scored against a loaded record has to align on those timestamps, and the
    # ones scored positionally read the values and ignore the index.
    time_index = resolve_time_index(ctx, n_timesteps=0)
    results = adapter.extract_observables(run_ctx, None, requests, time_index=time_index)

    observables: dict[str, ObservableResult] = {}
    simulated: dict[str, list[float]] = {}
    series: dict[str, pd.Series] = {}
    diagnostics: dict[str, float] = {}
    for name, output in outputs.items():
        result = results.get(name)
        if result is None or np.asarray(result.values).size == 0:
            raise NotImplementedError(f"Solver returned no calibration values for output {name!r}")
        if output.support == "network":
            thickness = _saturated_thickness_or_none(adapter, run_ctx, name, output, time_index)
            simulated[name], scored = score_network_output(
                run_ctx, name, output, result, saturated_thickness=thickness
            )
            diagnostics.update(scored)
            continue
        values = result.values
        dated = dated_series(result)
        if name in gauge_comparable and not getattr(result, "includes_runoff", False):
            if dated is None:
                raise NotImplementedError(
                    f"Output {name!r} scores a gauge record on the simulated discharge, "
                    "which needs the runoff forcing added on a time axis, and the solver "
                    "returned the values without one."
                )
            area_id = gauge_comparable[name]
            if area_id is None:
                # The whole-catchment series: the runoff forcing is areal over
                # that same basin, so it is added without a scaling area.
                dated = add_runoff_to_discharge(dated, ctx)
            else:
                area = float(np.asarray(results[area_id].values, dtype=float).reshape(-1)[0])
                fraction = report_the_area_a_gauge_drains(
                    str(getattr(output, "observes", "?")), ctx, area_m2=area, where=name
                )
                if fraction is not None:
                    diagnostics[f"{name}.drained_fraction"] = fraction
                dated = add_runoff_to_discharge(dated, ctx, area_m2=area)
            values = dated.to_numpy()
            result = replace(result, values=values, times=dated.index, includes_runoff=True)
        result = select_observable_times(result, output.time)
        dated = dated_series(result)
        observables[name] = result
        simulated[name] = slice_time(result.values, "all", output.reducer)
        if dated is not None:
            series[name] = dated
    return ExtractedOutputs(
        observables=observables, values=simulated, series=series, diagnostics=diagnostics
    )


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
        and request.support in ("cell", "domain")
        and getattr(output, "observes", None) is not None
    )


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


def station_xy(ctx: Any, station_id: str, *, variable: str) -> tuple[float, float] | None:
    """Return the coordinate a station's loaded record carries, or None.

    Only the opt-in gauge snap reads it for a discharge station: without a snap
    that coordinate lands off the routed talweg, which is why it is not used.
    """
    loaded = getattr(ctx, "loaded_data", None)
    records = getattr(loaded, OBSERVED_FAMILIES.get(variable, variable), None)
    for rec in getattr(records, "points", None) or []:
        if str(rec.station_id) == str(station_id):
            return _xy_from_record(rec)
    return None


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
    "point_xy_from_output",
    "require_release_flux_unit",
    "resolve_flow_adapter",
    "resolve_station_cells",
    "snap_gauge_cell",
    "station_xy",
]
