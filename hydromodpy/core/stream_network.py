"""What the model calls a stream, from a per-cell release flux.

The model does not produce a stream network, it produces sources. A cell where
the aquifer releases water to the surface is a point of appearance, not a reach;
the object comparable to a mapped stream network is what those sources generate
downslope. So the simulated network is the downslope closure of the seepage
pattern, traced to the outlet, and that closure is the physical model of the
source-to-stream transition rather than a patch over a discontinuous mask.

Nothing here names a solver package. The release flux arrives already
aggregated by the adapter, positive when the aquifer feeds the surface, which
is the whole point of the observable contract: deciding that a drain, a
gaining reach and a stream-role constant head all count as resurgence is the
backend's job, not this layer's.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.topographic_distance import DownslopeMetric


@dataclass(frozen=True, slots=True)
class SimulatedNetwork:
    """The seepage pattern and the stream network it generates."""

    seepage: np.ndarray
    """(n_cells,) bool: cells releasing more than their own threshold."""

    network: np.ndarray
    """(n_cells,) bool: the downslope closure of ``seepage``."""

    threshold_m3_s: np.ndarray
    """(n_cells,) the specific threshold actually applied, in m3/s."""

    @property
    def n_seepage(self) -> int:
        return int(self.seepage.sum())

    @property
    def n_network(self) -> int:
        return int(self.network.sum())

    @property
    def continuity(self) -> float:
        """Share of the network that is a source rather than a routed reach.

        One means the closure added nothing, so the sources already formed a
        network; a small value means a sparse pattern generating a long one.
        """
        n_network = self.n_network
        return float(self.n_seepage / n_network) if n_network else float("nan")


def specific_seepage_threshold(
    cell_area_m2: np.ndarray,
    mean_recharge_m_s: float,
    *,
    ratio: float,
) -> np.ndarray:
    """Return the per-cell flux below which a release is not a stream.

    The threshold is a *specific* flux, not a discharge: on a mesh with cells
    of different sizes a fixed m3/s cut would be nine times harsher on a cell
    three times smaller, and the network would follow the refinement rather
    than the physics. Reading: a cell releasing less than ``ratio`` of its own
    recharge is not a seepage face. ``ratio = 0`` reproduces the purely
    geometric criterion of the paper, which gives no threshold at all.
    """
    area = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    if float(ratio) < 0.0:
        raise ValueError(f"the threshold ratio must be positive, got {ratio}.")
    recharge = float(mean_recharge_m_s)
    if not np.isfinite(recharge) or recharge < 0.0:
        raise ValueError(f"the mean recharge must be finite and positive, got {recharge}.")
    return float(ratio) * recharge * area


def downstream_closure(metric: DownslopeMetric, mask: np.ndarray) -> np.ndarray:
    """Return the cells the water of ``mask`` flows through, ``mask`` included.

    One accumulation pass over the receiver graph is the closure, so no second
    traversal is written. Inactive cells come back as NaN from the
    accumulation, which is why the test is not ``> 0`` alone.
    """
    active = metric.graph.active
    seed = np.asarray(mask, dtype=bool).reshape(-1)
    if seed.size != active.size:
        raise ValueError(f"mask must have {active.size} cells, got {seed.size}.")
    accumulated = accumulate_on_downhill_graph(metric.graph, seed.astype(float))
    closed = np.zeros(seed.size, dtype=bool)
    finite = np.isfinite(accumulated)
    closed[finite] = accumulated[finite] > 0.0
    return closed & active


def build_simulated_network(
    release_flux: np.ndarray,
    *,
    threshold_m3_s: np.ndarray,
    metric: DownslopeMetric,
) -> SimulatedNetwork:
    """Turn a per-cell release flux into a seepage mask and its stream network.

    ``release_flux`` is ``(n_cells,)`` or ``(n_times, n_cells)`` in m3/s,
    positive when the aquifer feeds the surface. A transient stack is read at
    its last timestep: phase one of the method runs a single steady period, and
    a mask defined over several states would not be a state.

    The threshold is applied strictly, so a cell releasing exactly its
    threshold is not a stream, and the comparison is made on the flux rather
    than on ``head >= surface``. The flux is anchored by the mass balance,
    which the geometric test is not: the same model read geometrically loses
    most of its mask when the drain conductance moves, while its median cell
    flux holds over eight decades.
    """
    flux = np.asarray(release_flux, dtype=float)
    if flux.ndim == 2:
        flux = flux[-1, :]
    elif flux.ndim != 1:
        raise ValueError(f"release_flux must be (n_cells,) or (n_times, n_cells), got {flux.shape}")

    threshold = np.asarray(threshold_m3_s, dtype=float).reshape(-1)
    active = metric.graph.active
    if flux.size != active.size:
        raise ValueError(f"release_flux holds {flux.size} cells, the mesh holds {active.size}.")
    if threshold.size != active.size:
        raise ValueError(
            f"the threshold holds {threshold.size} cells, the mesh holds {active.size}."
        )

    seepage = np.isfinite(flux) & (flux > threshold) & active
    return SimulatedNetwork(
        seepage=seepage,
        network=downstream_closure(metric, seepage),
        threshold_m3_s=threshold,
    )


__all__ = (
    "SimulatedNetwork",
    "build_simulated_network",
    "downstream_closure",
    "specific_seepage_threshold",
)
