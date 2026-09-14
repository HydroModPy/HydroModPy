"""Observables both MODFLOW backends read the same way.

MODFLOW 6 and MODFLOW-NWT write the same FloPy-readable binaries, so discharge,
head and the per-cell fields come out of the same helpers. What differs stays
in each adapter: MODFLOW 6 also serves lake states and has to collapse a
structured station cell onto its DISV id.

The entry point serves what it can and hands back what it could not, so an
adapter adds its own observables on top and reports the remainder itself. That
is what replaces asking an adapter's signature what it supports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    require_unique_request_ids,
)
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.solver.base.observables import (
    field_observable,
    scalar_observable,
    series_observable,
)
from hydromodpy.solver.modflow_common.calibration_extractors import (
    ReleasePackage,
    extract_discharge_from_cbc,
    extract_head_from_hds,
    extract_release_flux_by_cell_from_cbc,
    extract_saturated_thickness_by_cell_from_hds,
)
from hydromodpy.solver.modflow_common.catchment_support import catchment_cell_mask
from hydromodpy.solver.modflow_common.discharge_routing import (
    flat_cell_index,
    route_release_to_discharge,
    routing_graph_for_model,
    upstream_area_m2,
)

RoutedDischargeReader = Callable[[Path, str, "pd.DatetimeIndex | None"], "pd.Series | None"]
StationCellMapper = Callable[[Mapping[str, tuple[int, int, int]]], dict[str, tuple[int, int, int]]]

_DISCHARGE_UNITS = "m3 s-1"
_HEAD_UNITS = "m"
_THICKNESS_UNITS = "m"

_DRAIN_RECORDS = ("DRN", "DRAIN", "DRAINS")
_DRAIN_TO_MOVER_RECORDS = ("DRN-TO-MVR",)
_STREAM_RECORDS = ("SFR",)
_LAKE_RECORDS = ("LAK", "LAKE", "LAK-GWF")
_SURFACE_TO_MOVER_RECORDS = ("SFR-TO-MVR", "LAK-TO-MVR")
_CONSTANT_HEAD_RECORDS = ("CHD", "CONSTANT HEAD")


def resolve_run_output(ctx: Any, *, name_attributes: Sequence[str]) -> tuple[Path, Any, str]:
    """Return the scratch directory, the model and the model name for a run.

    A lightweight trial writes nothing to the store, so the only trace of the
    run is the scratch directory the execution registry recorded.
    """
    output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
    model = ctx.state.execution.models_by_run_id.get(ctx.run.id)
    if output_dir is None or model is None:
        raise ObservableNotAvailableError(f"No solver output recorded for run {ctx.run.id!r}")
    model_name = next(
        (
            value
            for value in (getattr(model, attr, None) for attr in name_attributes)
            if value is not None
        ),
        None,
    )
    if model_name is None:
        raise ObservableNotAvailableError(f"Model name is missing for run {ctx.run.id!r}")
    return Path(output_dir), model, str(model_name)


def _stream_role_cells(model: Any) -> np.ndarray | None:
    """Cells whose CHD rows carry the stream role, as the builder recorded them.

    The MF6 build stores the mask it used to place the stream boundary, and it
    is the only thing that tells a stream CHD apart from an ocean or a side CHD
    once they share a single package in the budget.
    """
    mask = getattr(model, "_stream_support_mask", None)
    if mask is None:
        return None
    flat = np.asarray(mask, dtype=bool).reshape(-1)
    return flat if bool(flat.any()) else None


def _drain_routes_to_mover(model: Any) -> bool:
    """True when the DRN package hands part of its flux to the water mover.

    MF6 subtracts the moved flux from the DRN term of the model budget, so DRN
    and DRN-TO-MVR are disjoint halves of one seepage, never a total and its
    subset. Only the MF6 package carries the option; the NWT drain has no
    ``mover`` attribute and answers False.
    """
    mover = getattr(getattr(model, "drn", None), "mover", None)
    if mover is None:
        return False
    return bool(mover.get_data())


def release_packages_for_model(model: Any) -> list[ReleasePackage]:
    """Declare the packages that release groundwater to the surface on this run.

    The builder drops the DRN rows of every cell an SFR reach or a stream-role
    CHD already owns, so reading DRN alone reports dry land exactly where a
    stream-network calibration aims. Under ``route_drainage`` the seepage of a
    hillslope cell also leaves the DRN term for DRN-TO-MVR, which is why that
    record joins the union whenever the DRN package feeds the mover. A package
    the run never built is skipped; a package it built keeps its record
    mandatory downstream.
    """
    packages: list[ReleasePackage] = []
    if getattr(model, "drn", None) is not None:
        packages.append(ReleasePackage(name="DRN", record_aliases=_DRAIN_RECORDS))
        if _drain_routes_to_mover(model):
            packages.append(
                ReleasePackage(name="DRN-TO-MVR", record_aliases=_DRAIN_TO_MOVER_RECORDS)
            )
    if getattr(model, "sfr", None) is not None:
        packages.append(ReleasePackage(name="SFR", record_aliases=_STREAM_RECORDS))
    if getattr(model, "lak", None) is not None:
        # The model budget carries the per-cell aquifer-to-lake exchange, beside
        # the per-lake budget the LAK builder also writes to its own file. A run
        # with a lake used to refuse the union rather than under-count it.
        packages.append(ReleasePackage(name="LAK", record_aliases=_LAKE_RECORDS))
    stream_cells = _stream_role_cells(model)
    if getattr(model, "chd", None) is not None and stream_cells is not None:
        packages.append(
            ReleasePackage(
                name="CHD",
                record_aliases=_CONSTANT_HEAD_RECORDS,
                cell_mask=stream_cells,
            )
        )
    if not packages:
        raise ObservableNotAvailableError(
            "release_flux needs a package that releases groundwater to the surface, and "
            "this run declares no DRN, no SFR, no LAK and no stream-role CHD."
        )
    return packages


def excluded_release_records_for_model(model: Any) -> dict[str, str]:
    """Budget records this run writes that are NOT a release to the surface.

    Declaring an exclusion is not the same as forgetting one. The union is
    checked against the records the FILE holds, so a release record no package
    reads refuses the run rather than reading as dry land; a record the model
    looked at and ruled out has to say so, or every run with a lateral boundary
    is refused for carrying one.

    The reason travels with the record, because "CHD is excluded" is only safe
    while it means "this CHD holds no stream".

    Keyed on the stream-role mask alone, never on which package attribute a
    backend happens to expose: MODFLOW-NWT builds its lateral boundary without
    a ``chd`` attribute on the model, so asking for one ruled nothing out and
    refused every NWT catchment for closing on a boundary.

    The surface-package mover records are ruled out unconditionally: they are a
    property of what a mover IS, not of how this run is built.
    """
    excluded: dict[str, str] = {}

    # A mover record on a SURFACE package carries water between surface features,
    # not across the aquifer boundary: it was already counted where it left the
    # aquifer (DRN, SFR or LAK), and adding it would count the same water twice.
    # DRN-TO-MVR is the opposite case and stays in the union: the drain takes it
    # OUT of the aquifer, and MF6 makes DRN and DRN-TO-MVR disjoint halves.
    surface_mover_reason = (
        "a mover record on a surface package moves water between surface features and "
        "never crosses the aquifer boundary, so it was already counted where it left "
        "the aquifer and counting it again would double the same water"
    )
    for record in _SURFACE_TO_MOVER_RECORDS:
        excluded[record] = surface_mover_reason

    if _stream_role_cells(model) is not None:
        return excluded
    reason = (
        "no cell of the constant head carries the stream role, so it is an ocean or a "
        "lateral boundary: water crossing it leaves the domain sideways instead of "
        "surfacing, and counting it would put a stream on the model edge"
    )
    excluded["CHD"] = reason
    excluded["CONSTANT HEAD"] = reason
    return excluded


def _aquifer_bounds(model: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return the top and the base of the aquifer, one value per cell."""
    mesh = getattr(model, "solver_mesh", None)
    if mesh is None:
        raise ObservableNotAvailableError(
            "saturated_thickness needs a solver mesh on the run model."
        )
    top = np.asarray(mesh.top, dtype=float).reshape(-1)
    botm = np.asarray(mesh.botm, dtype=float)
    if botm.ndim == 1:
        botm = botm.reshape(1, -1)
    return top, botm[-1].reshape(-1)


def extract_common_modflow_observables(
    output_dir: Path,
    model_name: str,
    model: Any,
    requests: Sequence[ObservableRequest],
    *,
    time_index: pd.DatetimeIndex | None = None,
    station_cell_mapper: StationCellMapper | None = None,
    routed_discharge_reader: RoutedDischargeReader | None = None,
    reach_flow_reader: Any | None = None,
) -> tuple[dict[str, ObservableResult], list[ObservableRequest]]:
    """Serve the shared MODFLOW observables; return the ones left unserved.

    Every head request is read in one pass over the head file, which is the
    point of taking the whole batch: a run with twenty piezometers opens the
    binary once instead of twenty times.
    """
    served: dict[str, ObservableResult] = {}
    unserved: list[ObservableRequest] = []
    if not requests:
        return served, unserved
    require_unique_request_ids(requests)

    head_requests = [r for r in requests if r.name == "head" and r.support == "cell"]
    discharge_requests = [r for r in requests if r.name == "discharge" and r.support == "domain"]
    discharge_cell_requests = [r for r in requests if r.name == "discharge" and r.support == "cell"]
    area_requests = [r for r in requests if r.name == "upstream_area" and r.support == "cell"]
    release_requests = [r for r in requests if r.name == "release_flux" and r.support == "cells"]
    thickness_requests = [
        r for r in requests if r.name == "saturated_thickness" and r.support == "cells"
    ]
    handled = {id(r) for r in head_requests + discharge_requests + discharge_cell_requests}
    handled |= {id(r) for r in release_requests + thickness_requests + area_requests}
    unserved = [r for r in requests if id(r) not in handled]

    if discharge_requests:
        # A routed network owns the discharge observable. With route_drainage the
        # in-catchment drainage has been moved into DRN-TO-MVR, so the plain DRAIN
        # record left in the budget is the buffer drainage of the neighbouring
        # basins and summing it would score the wrong water. The reader is injected
        # by the backend: SFR is MODFLOW 6 only, and `modflow_common` must not
        # import a backend.
        series = None
        routed = False
        if routed_discharge_reader is not None:
            series = routed_discharge_reader(output_dir, model_name, time_index)
            routed = series is not None
        if series is None:
            series = extract_discharge_from_cbc(
                output_dir,
                model_name,
                time_index,
                catchment_mask=catchment_cell_mask(model),
            )
        for request in discharge_requests:
            served[request.id] = series_observable(
                request, series, units=_DISCHARGE_UNITS, includes_runoff=routed
            )

    if head_requests:
        station_cells = {r.id: r.cell for r in head_requests}
        if station_cell_mapper is not None:
            station_cells = station_cell_mapper(station_cells)
        series_by_station = extract_head_from_hds(
            output_dir,
            model_name,
            station_cells=station_cells,
            time_index=time_index,
        )
        for request in head_requests:
            try:
                series = series_by_station[request.id]
            except KeyError as exc:
                raise ObservableNotAvailableError(
                    f"No head series extracted for station {request.id!r}"
                ) from exc
            served[request.id] = series_observable(request, series, units=_HEAD_UNITS)

    if area_requests:
        # Static geometry, but it belongs with the discharge: the runoff a gauge
        # sees has to be the runoff over exactly the cells whose release it sees.
        graph = routing_graph_for_model(
            model, diagonal_neighbors=any(r.diagonal_neighbors for r in area_requests)
        )
        areas = upstream_area_m2(model, graph, catchment_mask=catchment_cell_mask(model))
        for request in area_requests:
            served[request.id] = scalar_observable(
                request, float(areas[flat_cell_index(model, request.cell)]), units="m2"
            )

    if release_requests or discharge_cell_requests:
        frame = extract_release_flux_by_cell_from_cbc(
            output_dir,
            model_name,
            packages=release_packages_for_model(model),
            excluded_records=excluded_release_records_for_model(model),
            time_index=time_index,
            n_cells=_n_cells(model),
        )
        for request in release_requests:
            served[request.id] = field_observable(request, frame, units=_DISCHARGE_UNITS)

        if discharge_cell_requests:
            # A routed network needs no post-processing: MODFLOW made the water
            # flow, movers included, so the reach under the gauge already holds
            # the simulated discharge. Reading it is both simpler and truer than
            # accumulating what entered the network, because it carries the
            # channel storage and the diversions the routing applied.
            reach_flow = reach_flow_reader(output_dir, model_name) if reach_flow_reader else None

            routed = None
            unrouted = [
                request
                for request in discharge_cell_requests
                if reach_flow is None or flat_cell_index(model, request.cell) not in reach_flow
            ]
            if unrouted:
                # No reach under that gauge: sum what the aquifer released above
                # it. The release is the union of every package crossing the
                # aquifer face, so this holds for DRN, LAK and the movers alike.
                graph = routing_graph_for_model(
                    model, diagonal_neighbors=any(r.diagonal_neighbors for r in unrouted)
                )
                routed = route_release_to_discharge(
                    frame.to_numpy(),
                    graph,
                    catchment_mask=catchment_cell_mask(model),
                )

            for request in discharge_cell_requests:
                index = flat_cell_index(model, request.cell)
                if reach_flow is not None and index in reach_flow:
                    values = np.asarray(reach_flow[index], dtype=float)
                    # The reach carries the runoff the network was fed with.
                    includes_runoff = True
                else:
                    values = routed[:, index]
                    includes_runoff = False
                series = pd.Series(values, index=frame.index[: values.size], name="discharge")
                served[request.id] = series_observable(
                    request, series, units=_DISCHARGE_UNITS, includes_runoff=includes_runoff
                )

    if thickness_requests:
        top, bottom = _aquifer_bounds(model)
        frame = extract_saturated_thickness_by_cell_from_hds(
            output_dir,
            model_name,
            top=top,
            bottom=bottom,
            time_index=time_index,
        )
        for request in thickness_requests:
            served[request.id] = field_observable(request, frame, units=_THICKNESS_UNITS)

    return served, unserved


def _n_cells(model: Any) -> int | None:
    """Cell count of the run mesh, so layers are summed onto the cell index."""
    mesh = getattr(model, "solver_mesh", None)
    if mesh is None:
        return None
    n_cells = getattr(mesh, "n_cells", None)
    return None if n_cells is None else int(n_cells)


__all__ = (
    "extract_common_modflow_observables",
    "release_packages_for_model",
    "resolve_run_output",
)
