"""The two priority floods of a routing surface, and what separates them.

A flood seeded on every escape of the mesh raises the closed depressions and
nothing else. A flood seeded on the outlet alone raises what the stream criterion
raises before it measures a distance to that single cell. The depression map
draws both; the computation lives here so a figure only draws.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.catchment.drainage.distance import (
    build_downslope_metric,
    downslope_distance_to_mask,
)
from hydromodpy.catchment.drainage.filling import DEFAULT_EPSILON_M, fill_depressions_on_graph
from hydromodpy.results.derive.stream_network.routing_surface import RoutingSurface


@dataclass(frozen=True, slots=True)
class Flood:
    """One priority flood of a surface, and what it had to raise."""

    seeds: np.ndarray
    """(n_cells,) bool: the cells the flood was allowed to leave through."""

    filled: np.ndarray
    """(n_cells,) elevations after the flood, NaN off the active mesh."""

    fill_m: np.ndarray
    """(n_cells,) filled minus persisted, in meters, NaN off the active mesh."""

    raised: np.ndarray
    """(n_cells,) bool: cells the flood had to lift onto a spill level."""

    @property
    def deepest_m(self) -> float:
        """The largest fill applied, zero when the flood raised nothing."""
        return float(self.fill_m[self.raised].max()) if self.raised.any() else 0.0


@dataclass(frozen=True, slots=True)
class DepressionFill:
    """Both floods of one routing surface, and what separates them."""

    surface: RoutingSurface

    closed: Flood
    """Seeded on every escape: the cells that cannot get out of the domain."""

    to_outlet: Flood
    """Seeded on the outlet alone: what the stream criterion floods."""

    stranded_fraction: float
    """Share of the support whose descent still misses the sealed outlet.

    Zero is the only healthy answer: after a flood seeded on one cell, every
    path of the support ends there by construction. Anything else means the
    surface the flood conditioned is not the one the descent walks, which is
    what a mismatched neighborhood produces.
    """

    @property
    def cut_off(self) -> np.ndarray:
        """(n_cells,) bool: raised by the outlet flood, in no depression.

        These cells drain, and not to this outlet. They are the whole reason
        the two readings must not share a name: on the Nancon they are fifteen
        thousand of the eighteen thousand the criterion's flood raises.
        """
        return self.to_outlet.raised & ~self.closed.raised

    @property
    def pitted_and_unreachable(self) -> np.ndarray:
        """(n_cells,) bool: raised by both floods, so genuinely in a pit."""
        return self.to_outlet.raised & self.closed.raised


def depression_fill(surface: RoutingSurface) -> DepressionFill:
    """Flood ``surface`` twice, and measure what the two answers do not share.

    Once from every escape, which raises the closed depressions and nothing
    else, and once from the outlet alone, which is what the stream criterion
    does before it measures a distance to that single cell.

    Both floods and the descent that checks the second walk the SAME neighbor
    graph. Fed the eight-neighbor graph while the descent reads the
    four-neighbor one, a flood leaves every filled cell spilling over a
    diagonal the descent cannot take, and almost the whole catchment stops
    reaching the outlet. The metric below re-derives its adjacency from
    ``diagonal_neighbors`` through the two builders the surface already used,
    so the pair cannot drift.
    """
    active = surface.active
    original = np.where(active, surface.topography, np.nan)
    closed = _flood(surface, original, surface.escape_mask())
    to_outlet = _flood(surface, original, surface.outlet_mask())

    metric = build_downslope_metric(
        to_outlet.filled,
        surface.face_node_connectivity,
        vertices=surface.vertices,
        centroids=surface.centroids,
        inactive_mask=~active,
        diagonal_neighbors=surface.diagonal_neighbors,
    )
    distance = downslope_distance_to_mask(metric, surface.outlet_mask())
    support = surface.within_catchment(active)
    stranded = float(np.mean(~np.isfinite(distance[support]))) if support.any() else float("nan")
    return DepressionFill(
        surface=surface,
        closed=closed,
        to_outlet=to_outlet,
        stranded_fraction=stranded,
    )


def _flood(surface: RoutingSurface, original: np.ndarray, seeds: np.ndarray) -> Flood:
    """Run one priority flood of the surface over the graph it routes on."""
    report = fill_depressions_on_graph(original, surface.adjacency, seeds)
    fill_m = report.surface - original
    return Flood(
        seeds=seeds,
        filled=report.surface,
        fill_m=fill_m,
        raised=surface.active & (fill_m > DEFAULT_EPSILON_M / 2.0),
    )


__all__ = ("DepressionFill", "Flood", "depression_fill")
