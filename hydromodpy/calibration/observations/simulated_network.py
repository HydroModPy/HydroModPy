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

One flux is not a source: the numerical dribble a boundary package leaves on a
cell that is dry for every practical purpose. The threshold that rejects it is
a share of the water the model receives, never a share of what the cell itself
receives, and :func:`specific_seepage_threshold` carries the measurement that
decides between the two.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.logging import get_logger
from hydromodpy.core.topographic_distance import DownslopeMetric

logger = get_logger(__name__)

MAX_REJECTED_FLUX_SHARE = 0.01
"""Share of the released water above which the threshold is calibrating, not filtering.

Measured on the Nancon at the root of the criterion, by recomputing the
residual there and converting it through the local slope rather than by
re-running the search: a threshold rejecting 0.23 per cent of the release
displaces the root by under one per cent, one rejecting 2.0 per cent displaces
it by of order ten. Eleven per cent is what separates two solvers on the same
catchment, so past this share the threshold is a second knob pulling against
the parameter being calibrated.
"""


@dataclass(frozen=True, slots=True)
class SimulatedNetwork:
    """The seepage pattern and the stream network it generates."""

    seepage: np.ndarray
    """(n_cells,) bool: cells releasing more than the threshold."""

    network: np.ndarray
    """(n_cells,) bool: the downslope closure of ``seepage``."""

    threshold_m3_s: np.ndarray
    """(n_cells,) the threshold actually applied, in m3/s, uniform over the mesh."""

    rejected_flux_share: float
    """Share of the released water the threshold sent back to dry land.

    The number that says whether the threshold acted as a floor or as a knob,
    per trial, rather than leaving it to be assumed.
    """

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
    """Return the flux below which a release is not a seepage face.

    The threshold is a share of what the model receives, ``ratio * R * A`` with
    ``A`` the area the mesh covers, so it is one number for the whole mesh.
    Reading: a cell releasing less than ``ratio`` of the water the model is fed
    is not a source. ``ratio = 0`` gives no threshold at all, which is the
    purely geometric criterion of the paper.

    ``A`` is the extent of the mesh, not of the catchment: on the Nancon,
    151.0 km2 against 67.3 km2. That is what makes ``R * A`` the total release
    exactly, and it leaves one residual: widening the buffer around the same
    catchment raises ``A`` and so raises ``tau`` at a fixed ratio. A declared
    ratio is therefore comparable across refinements of one domain, and not
    across two domains buffered differently.

    **Why the reference is the catchment and not the cell.** The definition this
    replaces was ``ratio * R * area[c]``, a share of the cell's own recharge,
    on the argument that a fixed m3/s cut would be nine times harsher on a cell
    three times smaller. That argument assumes the release is a surface flux
    which converges as the mesh is refined. It is not: a cell releases the
    drainage it collects from upslope, so ``q / (R * area)`` is a concentration
    factor and carries the mesh in its denominator. Measured on the Nancon by
    aggregating one solved field from 50 m to 400 m cells, its median falls
    from 49.6 to 4.1. A threshold on that quantity therefore selects whatever
    the discretisation gives it: at ``ratio = 100`` of the cell's own recharge
    it keeps 51 per cent of the released water at 50 m, 18 per cent at 100 m
    and nothing at 200 m, where a threshold placed at ``4.5e-4`` of the
    production keeps 94, 97, 99 and 99.6 per cent of it from 50 m to 400 m.
    ``R`` is a property of the forcing and ``A`` of the model domain, and
    neither moves when that domain is refined.

    That reference is also frozen over the search by construction rather than
    by convention, which the criterion requires: a threshold moving with the
    trial would cost ``D_so(K/R)`` its monotonicity. A steady model whose only
    sink is seepage returns every drop it receives, so ``R * A`` is also the
    total release at every trial. On the Nancon, 2.1018 m3/s of recharge
    against 2.1025 of drain outflow, unchanged from ``K = 1e-7`` to ``1e-3``.

    The name still says ``specific`` from the definition it replaces; renaming
    it belongs with the ``tau_specific_ratio`` field it reads, one atomic pass
    over the config, the generated reference and the example TOML files.
    """
    area = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    if float(ratio) < 0.0:
        raise ValueError(f"the threshold ratio must be positive, got {ratio}.")
    recharge = float(mean_recharge_m_s)
    if not np.isfinite(recharge) or recharge < 0.0:
        raise ValueError(f"the mean recharge must be finite and positive, got {recharge}.")
    finite = area[np.isfinite(area)]
    if finite.size == 0 or finite.sum() <= 0.0:
        raise ValueError("the mesh covers no finite area, so the model receives no water.")
    return np.full(area.size, float(ratio) * recharge * float(finite.sum()))


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

    How much water the threshold rejected is measured and published, and a
    threshold rejecting more than :data:`MAX_REJECTED_FLUX_SHARE` says so. Past
    that share it no longer filters the sources, it shortens the network, and
    shortening the network is what the calibrated parameter is there to do.
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
    released = np.isfinite(flux) & (flux > 0.0) & active
    total = float(flux[released].sum())
    rejected = float(flux[released & ~seepage].sum()) / total if total > 0.0 else 0.0
    if rejected > MAX_REJECTED_FLUX_SHARE:
        logger.warning(
            "The seepage threshold rejected %.2f%% of the released water, over the %.0f%% "
            "bound: it is no longer filtering the sources, it is shortening the simulated "
            "network, which is what the calibrated ratio is there to do. On one catchment, "
            "rejecting 2.0 per cent of the release displaced the root by of order ten per "
            "cent, where two solvers on the same data are 11 per cent apart. Lower the "
            "threshold ratio, or read the calibrated value as conditional on it.",
            100.0 * rejected,
            100.0 * MAX_REJECTED_FLUX_SHARE,
        )

    return SimulatedNetwork(
        seepage=seepage,
        network=downstream_closure(metric, seepage),
        threshold_m3_s=threshold,
        rejected_flux_share=rejected,
    )


__all__ = (
    "MAX_REJECTED_FLUX_SHARE",
    "SimulatedNetwork",
    "build_simulated_network",
    "downstream_closure",
    "specific_seepage_threshold",
)
