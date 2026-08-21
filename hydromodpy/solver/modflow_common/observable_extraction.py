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
from hydromodpy.solver.base.observables import field_observable, series_observable
from hydromodpy.solver.modflow_common.calibration_extractors import (
    extract_discharge_from_cbc,
    extract_drain_outflow_by_cell_from_cbc,
    extract_head_from_hds,
    extract_saturated_thickness_by_cell_from_hds,
)

StationCellMapper = Callable[[Mapping[str, tuple[int, int, int]]], dict[str, tuple[int, int, int]]]

_DISCHARGE_UNITS = "m3 s-1"
_HEAD_UNITS = "m"
_THICKNESS_UNITS = "m"


def resolve_run_output(ctx: Any, *, name_attributes: Sequence[str]) -> tuple[Path, Any, str]:
    """Return the scratch directory, the model and the model name for a run.

    A lightweight trial writes nothing to the store, so the only trace of the
    run is the scratch directory the execution registry recorded.
    """
    output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
    model = ctx.state.execution.models_by_run_id.get(ctx.run.id)
    if output_dir is None or model is None:
        raise RuntimeError(f"No solver output recorded for run {ctx.run.id!r}")
    model_name = next(
        (
            value
            for value in (getattr(model, attr, None) for attr in name_attributes)
            if value is not None
        ),
        None,
    )
    if model_name is None:
        raise RuntimeError(f"Model name is missing for run {ctx.run.id!r}")
    return Path(output_dir), model, str(model_name)


def _aquifer_bounds(model: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return the top and the base of the aquifer, one value per cell."""
    mesh = getattr(model, "solver_mesh", None)
    if mesh is None:
        raise RuntimeError("saturated_thickness needs a solver mesh on the run model.")
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
    release_requests = [r for r in requests if r.name == "release_flux" and r.support == "cells"]
    thickness_requests = [
        r for r in requests if r.name == "saturated_thickness" and r.support == "cells"
    ]
    handled = {id(r) for r in head_requests + discharge_requests}
    handled |= {id(r) for r in release_requests + thickness_requests}
    unserved = [r for r in requests if id(r) not in handled]

    if discharge_requests:
        series = extract_discharge_from_cbc(output_dir, model_name, time_index)
        for request in discharge_requests:
            served[request.id] = series_observable(request, series, units=_DISCHARGE_UNITS)

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
                raise KeyError(f"No head series extracted for station {request.id!r}") from exc
            served[request.id] = series_observable(request, series, units=_HEAD_UNITS)

    if release_requests:
        frame = extract_drain_outflow_by_cell_from_cbc(
            output_dir,
            model_name,
            time_index=time_index,
            n_cells=_n_cells(model),
        )
        for request in release_requests:
            served[request.id] = field_observable(request, frame, units=_DISCHARGE_UNITS)

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
    "resolve_run_output",
)
