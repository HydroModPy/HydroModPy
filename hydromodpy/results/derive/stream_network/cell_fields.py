"""Cell fields rebuilt from a run at read time: the network, its agreement, two distances.

``simulated_active_network``, ``network_agreement``, ``downslope_distance`` and
``depression_fill_depth`` are described in ``REBUILT_FIELDS`` and computed here,
one row per step and one value per cell, from the functions that already draw
the stream figures. The criterion graph takes 0.5 s to build and the masks of 36
steps 0.03 s once it exists, so the graph is held on the run object, and a
reader that asks for one step at a time still builds it once.

A flowing cell of the simulated network is the one its stack keeps: seepage above
the threshold, closed downstream on the criterion graph, and above the visible
flow of the sealed output. The agreement and the distance follow the comparison
the run scores instead (seepage and closure, no visible flow), so they give the
numbers of ``network_comparison_from_run``. The depression field is the closed
flood, the one the depression map draws.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.catchment.drainage.distance import downslope_distance_to_mask
from hydromodpy.catchment.stream_network.extent import CHUNK_ELEMENTS, flowing_cells
from hydromodpy.catchment.stream_network.geometry import NetworkGeometry, criterion_supports
from hydromodpy.catchment.stream_network.network import build_simulated_network
from hydromodpy.core.budget.terms import ACTING_PACKAGES
from hydromodpy.core.scoring.stream_defaults import VisibleFlow, parse_visible_flow
from hydromodpy.results.derive.run_memo import RunMemo
from hydromodpy.results.derive.stream_network.comparison import (
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
    AGREEMENT_VALID,
)
from hydromodpy.results.derive.stream_network.criterion_settings import (
    NetworkCriterionSettings,
    network_criterion_settings,
)
from hydromodpy.results.derive.stream_network.depressions import Flood, depression_fill
from hydromodpy.results.derive.stream_network.routing_surface import (
    routing_surface_from_run,
    unavailable_reason_for_routing,
)
from hydromodpy.results.derive.stream_network.run_extent import (
    FLOW_FIELD,
    flow_geometry_from_run,
    unavailable_reason_for_flow,
)
from hydromodpy.results.derive.virtual_fields import budget_terms_kept, package_cells_rows
from hydromodpy.results.run.geographic import field_steps

__all__ = (
    "REBUILT_FIELD_ROWS",
    "FlowGeometry",
    "RebuiltField",
    "depression_flood_of",
    "flow_geometry_of",
    "rebuilt_rows",
    "rebuilt_unavailable",
)

_MEMO = RunMemo()


@dataclass(frozen=True, slots=True)
class FlowGeometry:
    """The criterion graph of a run and the visible flow its output was scored with."""

    geometry: NetworkGeometry
    visible: VisibleFlow


@dataclass(frozen=True, slots=True)
class RebuiltField:
    """How one rebuilt field is computed and when a run can serve it."""

    rows: Callable[[Any, Sequence[int]], np.ndarray]
    """``(len(steps), n_cells)`` float64, one row per step asked."""

    unavailable: Callable[[Any], str | None]
    """Why the run cannot serve the field, None when it can."""

    static: bool = False
    """True when every row is the same, whatever the step."""


def _settings_of(run: Any) -> NetworkCriterionSettings:
    return _MEMO.get_or_build(run, "settings", lambda: network_criterion_settings(run))


def flow_geometry_of(run: Any) -> FlowGeometry:
    """Return the criterion graph of ``run``, built once for the life of the run object."""

    def build() -> FlowGeometry:
        settings = _settings_of(run)
        geometry = flow_geometry_from_run(
            run,
            tau_specific_ratio=settings.tau_specific_ratio,
            diagonal_neighbors=settings.diagonal_neighbors,
            observed_rasterization=settings.observed_rasterization,
            observed_position_accuracy_m=settings.observed_position_accuracy_m,
            heads_snap_radius_m=settings.heads_snap_radius_m,
            heads_min_drained_area_km2=settings.heads_min_drained_area_km2,
        )
        return FlowGeometry(geometry, parse_visible_flow(settings.extent_rules.visible_flow))

    return _MEMO.get_or_build(run, "flow", build)


def depression_flood_of(run: Any) -> tuple[Flood, np.ndarray]:
    """Return the closed flood of ``run`` and the cells of its active mesh, built once."""

    def build() -> tuple[Flood, np.ndarray]:
        surface = routing_surface_from_run(
            run, diagonal_neighbors=_settings_of(run).diagonal_neighbors
        )
        return depression_fill(surface).closed, surface.active

    return _MEMO.get_or_build(run, "depression", build)


def _flowing(run: Any, steps: Sequence[int]) -> tuple[np.ndarray, NetworkGeometry]:
    """Return the ``(len(steps), n_cells)`` bool masks of the flowing cells, and the graph."""
    flow = flow_geometry_of(run)
    geometry = flow.geometry
    n_cells = int(geometry.metric.graph.active.size)
    order = [int(step) for step in steps]
    flowing = np.zeros((len(order), n_cells), dtype=bool)
    per_pass = max(1, CHUNK_ELEMENTS // max(1, n_cells))
    for first in range(0, len(order), per_pass):
        chunk = order[first : first + per_pass]
        releases = np.asarray(field_steps(run, FLOW_FIELD, chunk), dtype=float)
        for offset, release in enumerate(releases.reshape(len(chunk), -1)):
            state = flowing_cells(
                release,
                threshold_m3_s=geometry.threshold_m3_s,
                metric=geometry.metric,
                visible_flow=flow.visible,
                outlet=geometry.outlet,
            )
            flowing[first + offset] = np.asarray(state.flowing, dtype=bool).reshape(-1)
    return flowing, geometry


def _network_rows(run: Any, steps: Sequence[int]) -> np.ndarray:
    return _flowing(run, steps)[0].astype("float64")


def _scored_states(run: Any, steps: Sequence[int]) -> list[tuple[np.ndarray, Any, NetworkGeometry]]:
    """Return, per step, the simulated network and the supports of the comparison the run scores.

    This is the rule of ``network_comparison_from_run``: seepage above the threshold and
    the downstream closure, with no visible flow.
    """
    geometry = flow_geometry_of(run).geometry
    n_cells = int(geometry.metric.graph.active.size)
    order = [int(step) for step in steps]
    states = []
    per_pass = max(1, CHUNK_ELEMENTS // max(1, n_cells))
    for first in range(0, len(order), per_pass):
        releases = np.asarray(field_steps(run, FLOW_FIELD, order[first : first + per_pass]))
        for release in releases.reshape(-1, n_cells):
            simulated = build_simulated_network(
                release, threshold_m3_s=geometry.threshold_m3_s, metric=geometry.metric
            )
            supports = criterion_supports(
                simulated=simulated,
                observed=geometry.observed,
                catchment=geometry.catchment,
                active=geometry.metric.graph.active,
                excluded=geometry.excluded,
            )
            states.append((simulated.network, supports))
    return [(network, supports, geometry) for network, supports in states]


def _agreement_rows(run: Any, steps: Sequence[int]) -> np.ndarray:
    states = _scored_states(run, steps)
    rows = np.full((len(states), states[0][2].metric.graph.active.size), float(AGREEMENT_NEITHER))
    for row, (_, supports, _) in zip(rows, states, strict=True):
        row[supports.missing] = AGREEMENT_MISSING
        row[supports.excess] = AGREEMENT_EXCESS
        row[supports.valid] = AGREEMENT_VALID
    return rows


def _distance_rows(run: Any, steps: Sequence[int]) -> np.ndarray:
    """Join the descent length to the map on simulated-only cells and to the network elsewhere."""
    states = _scored_states(run, steps)
    distance = np.full((len(states), states[0][2].metric.graph.active.size), np.nan)
    for row, (network, supports, geometry) in zip(distance, states, strict=True):
        row[supports.excess] = np.asarray(geometry.distance_to_observed, dtype=float)[
            supports.excess
        ]
        if supports.missing.any():
            to_network = downslope_distance_to_mask(geometry.metric, network)
            row[supports.missing] = to_network[supports.missing]
    distance[~np.isfinite(distance)] = np.nan
    return distance


def _depression_rows(run: Any, steps: Sequence[int]) -> np.ndarray:
    flood, active = depression_flood_of(run)
    row = np.where(active, np.where(flood.raised, flood.fill_m, 0.0), np.nan)
    return np.tile(row, (len(steps), 1))


def _package_rows(run: Any, steps: Sequence[int]) -> np.ndarray:
    """Read the package codes from the stored budget, which needs no graph and no memo."""
    order = [int(step) for step in steps]
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        first = min(order)
        rows = package_cells_rows(sz.root, first, max(order) + 1)
    finally:
        sz.close()
    return rows[[step - first for step in order]]


def _package_unavailable(run: Any) -> str | None:
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        budget = sz.root.get("budget")
        if budget is None or not any(t in budget for _, terms in ACTING_PACKAGES for t in terms):
            return "run kept no budget term of a boundary package"
        if not budget_terms_kept(sz.root, "package_cells"):
            return "run did not keep every budget term of the boundary packages"
        return None
    finally:
        sz.close()


def _flow_unavailable(run: Any) -> str | None:
    return unavailable_reason_for_flow(run, tau_specific_ratio=_settings_of(run).tau_specific_ratio)


REBUILT_FIELD_ROWS: dict[str, RebuiltField] = {
    "simulated_active_network": RebuiltField(_network_rows, _flow_unavailable),
    "network_agreement": RebuiltField(_agreement_rows, _flow_unavailable),
    "downslope_distance": RebuiltField(_distance_rows, _flow_unavailable),
    "package_cells": RebuiltField(_package_rows, _package_unavailable),
    "depression_fill_depth": RebuiltField(
        _depression_rows, unavailable_reason_for_routing, static=True
    ),
}
"""One row per field of ``REBUILT_FIELDS``, which holds its descriptor."""


def _rebuilt_row(name: str) -> RebuiltField:
    try:
        return REBUILT_FIELD_ROWS[name]
    except KeyError:
        raise KeyError(
            f"Rebuilt field {name!r} has no row in REBUILT_FIELD_ROWS "
            "(hydromodpy/results/derive/stream_network/cell_fields.py). Add one."
        ) from None


def rebuilt_unavailable(run: Any, name: str) -> str | None:
    """Return why ``run`` cannot serve the rebuilt field ``name``, None when it can."""
    return _MEMO.get_or_build(
        run, ("unavailable", name), lambda: _rebuilt_row(name).unavailable(run)
    )


def rebuilt_rows(run: Any, name: str, steps: Sequence[int]) -> np.ndarray:
    """Return the rows of the rebuilt field ``name`` at ``steps``, on the caller's run.

    Raises
    ------
    ValueError
        The run lacks what the field is built from, as the stack of the
        simulated network has always refused it.
    """
    reason = rebuilt_unavailable(run, name)
    if reason is not None:
        raise ValueError(f"{name} is not available for this run: {reason}.")
    return _rebuilt_row(name).rows(run, steps)
