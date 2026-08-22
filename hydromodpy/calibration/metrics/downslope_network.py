"""The signed gap between an excess of simulated stream and a missing one.

For every cell where the model releases water, trace the descent to the mapped
stream network and measure it; average over the simulated network to get
``D_so``. Reciprocally, from every mapped cell, the descent to the simulated
network averages to ``D_os``. The criterion is

    J_signed = D_so - D_os        the residual a root search drives to zero
    J        = abs(J_signed)      the cost, Eq. 1 of the paper
    Doptim   = (D_so + D_os) / 2  Eq. 2, a diagnostic and never the cost
    roptim   = Doptim / L_ref     Eq. 3, the validity indicator

``D_so`` large means a network spilling far outside the mapped one; ``D_os``
large means one that never grew. Zero is the balance between excess and
missing, that is the intersection of two curves, not the minimum of a
distance. Minimising ``Doptim`` instead is a different estimator: it does have
an interior minimum, but nothing puts that minimum at the crossing.

The two supports are treated differently on purpose. The simulated network is
closed downslope, the mapped one is taken raw, and one single cell is added to
the target of ``D_so``: the outlet. Closing the mapped network instead would
build observation out of the DEM, and it erases the very signal Eq. 4 exists to
detect, turning a misregistered network from rejected into accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from hydromodpy.calibration.observations.simulated_network import SimulatedNetwork
from hydromodpy.core.topographic_distance import (
    DownslopeMetric,
    downslope_distance_to_mask,
    mean_downslope_distance,
)

Weighting = Literal["cell", "area"]

DISTANCE_METHOD = "downslope_simclosed_obsraw_outletsealed"
"""The one label this criterion publishes, produced in this one place.

The field used to be a free string carrying three different names for a single
algorithm, which made it commentary rather than provenance.
"""


@dataclass(frozen=True, slots=True)
class SeepageDistanceResult:
    """The cost, the signed residual and everything needed to read them."""

    cost: float
    """``J``, what the optimizer minimises."""

    signed_gap: float
    """``J_signed``. It travels in the components, never in the cost, so that
    picking the best trial by lowest cost gives the trial closest to zero and
    not the most negative one."""

    optimal_distance: float
    """``Doptim``. An indicator. It cannot separate two models at the same
    ``J``, and ``J`` cannot separate two structures at the same ``Doptim``."""

    status: Literal["ok", "empty_network", "failed"]
    components: dict[str, float]


def _support_statistics(
    distance: np.ndarray,
    support: np.ndarray,
    *,
    weights: np.ndarray | None,
    cap_m: float,
) -> dict[str, float]:
    """Return the mean plus the tail shape of one distance over one support."""
    summary = mean_downslope_distance(distance, support, weights=weights, saturation_cap_m=cap_m)
    values = np.where(np.isinf(distance), cap_m, distance)[support & ~np.isnan(distance)]
    if values.size == 0:
        return {
            "mean": float("nan"),
            "median": float("nan"),
            "p90": float("nan"),
            "top5_share": float("nan"),
            "zero_fraction": float("nan"),
            "n_support": float(summary.n_support),
            "n_unreachable": float(summary.n_unreachable),
        }
    total = float(values.sum())
    top5 = np.sort(values)[::-1][: max(1, values.size // 20)]
    return {
        "mean": summary.mean_m,
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "top5_share": float(top5.sum() / total) if total > 0.0 else 0.0,
        "zero_fraction": float(np.mean(values == 0.0)),
        "n_support": float(summary.n_support),
        "n_unreachable": float(summary.n_unreachable),
    }


def seepage_distance_cost(
    *,
    simulated: SimulatedNetwork,
    observed: np.ndarray,
    outlet: int,
    catchment: np.ndarray,
    metric: DownslopeMetric,
    distance_to_observed: np.ndarray,
    distance_to_observed_raw: np.ndarray,
    cell_area_m2: np.ndarray,
    length_scale_m: float,
    saturation_cap_m: float,
    excluded: np.ndarray | None = None,
    weighting: Weighting = "cell",
    max_unreachable_fraction: float = 0.05,
    roptim_max: float = 2.0,
) -> SeepageDistanceResult:
    """Evaluate the signed gap for one trial.

    ``distance_to_observed`` is the descent length to the mapped network with
    the outlet sealed in, and ``distance_to_observed_raw`` the same without it.
    Both depend only on the topography, so a calibration computes them once and
    passes them in at every trial; only the distance to the simulated network
    is recomputed here.

    Both supports are intersected with the topographic catchment, which is not
    a detail: on the buffered model domain a tenth of the cells drain outside
    the basin and never meet the mapped network, so the unreachable guard would
    abort on every real catchment and the excess would pollute ``D_so`` with
    paths that mean nothing. Measured on a real mesh, the same criterion sees
    15 per cent unreachable over the active mesh and 0.1 per cent over its
    catchment.

    Water-body cells go in ``excluded``: they stay in the graph so an upslope
    cell can still descend through the reservoir, and they stay in the target
    so a seepage cell fifty metres from the bank stops there, but they leave
    both supports. Keeping them in the support of ``D_so`` would inject one
    zero per lake cell and move the root with the size of the reservoir rather
    than with the hydrogeology.
    """
    active = metric.graph.active
    observed_mask = np.asarray(observed, dtype=bool).reshape(-1)
    catchment_mask = np.asarray(catchment, dtype=bool).reshape(-1)
    keep = catchment_mask & active
    if excluded is not None:
        keep = keep & ~np.asarray(excluded, dtype=bool).reshape(-1)

    support_so = simulated.network & keep
    support_os = observed_mask & keep
    if not np.any(support_os):
        raise ValueError(
            "the observed stream network holds no cell inside the catchment: check its "
            "geometry, its CRS and the outlet the catchment was delineated from."
        )

    weights = np.asarray(cell_area_m2, dtype=float).reshape(-1) if weighting == "area" else None
    distance_to_simulated = downslope_distance_to_mask(metric, simulated.network)

    so = _support_statistics(
        distance_to_observed, support_so, weights=weights, cap_m=saturation_cap_m
    )
    os_ = _support_statistics(
        distance_to_simulated, support_os, weights=weights, cap_m=saturation_cap_m
    )

    # Both weightings are always reported: their gap measures directly what the
    # mesh refinement does to the criterion, since a corridor refined along the
    # streams carries more cells per unit area exactly where distances are
    # smallest.
    by_cell_so = mean_downslope_distance(
        distance_to_observed, support_so, saturation_cap_m=saturation_cap_m
    ).mean_m
    by_cell_os = mean_downslope_distance(
        distance_to_simulated, support_os, saturation_cap_m=saturation_cap_m
    ).mean_m
    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    by_area_so = mean_downslope_distance(
        distance_to_observed, support_so, weights=areas, saturation_cap_m=saturation_cap_m
    ).mean_m
    by_area_os = mean_downslope_distance(
        distance_to_simulated, support_os, weights=areas, saturation_cap_m=saturation_cap_m
    ).mean_m

    d_so = so["mean"]
    d_os = os_["mean"]
    status: Literal["ok", "empty_network", "failed"] = "ok"
    if simulated.n_network == 0 or not np.any(support_so):
        # The high end of the bracket: no network at all. The residual is
        # defined and negative, which is what a root search needs; a large
        # positive penalty here would destroy the sign structure it brackets on.
        status = "empty_network"
        d_so = float("nan")
        signed_gap = -saturation_cap_m
        optimal = float("nan")
    else:
        signed_gap = float(d_so - d_os)
        optimal = 0.5 * float(d_so + d_os)

    n_support_so = max(so["n_support"], 1.0)
    n_support_os = max(os_["n_support"], 1.0)
    frac_unreachable_so = so["n_unreachable"] / n_support_so
    frac_unreachable_os = os_["n_unreachable"] / n_support_os
    if status == "ok" and max(frac_unreachable_so, frac_unreachable_os) > float(
        max_unreachable_fraction
    ):
        # Beyond a few per cent the surface is not conditioned and the number
        # would be a fiction. Filtering the unreachable cells away instead is
        # exactly the silent failure this guard exists to prevent. An empty
        # network is exempt: every observed cell is then unreachable by
        # definition, not because the surface is unusable, and that end of the
        # bracket has to stay evaluable.
        status = "failed"

    roptim = optimal / float(length_scale_m) if np.isfinite(optimal) else float("nan")
    counts_valid = int(np.sum(support_so & observed_mask))
    counts_excess = int(np.sum(support_so & ~observed_mask))
    counts_missing = int(np.sum(support_os & ~simulated.network))

    # Share of the simulated support whose descent meets the target only at the
    # sealed outlet: it says how much of D_so rests on that one added cell.
    outlet_only = np.isinf(distance_to_observed_raw) & support_so
    frac_outlet = float(outlet_only.sum() / n_support_so)

    seepage_support = simulated.seepage & keep
    d_so_seepage_only = mean_downslope_distance(
        distance_to_observed,
        seepage_support,
        weights=weights,
        saturation_cap_m=saturation_cap_m,
    ).mean_m

    components = {
        "D_so": d_so,
        "D_os": d_os,
        "J": abs(signed_gap),
        "J_signed": signed_gap,
        "Doptim": optimal,
        "roptim": roptim,
        "roptim_valid": float(roptim <= float(roptim_max)) if np.isfinite(roptim) else 0.0,
        "D_so_seepage_only": d_so_seepage_only,
        "D_so_median": so["median"],
        "D_so_p90": so["p90"],
        "D_so_top5_share": so["top5_share"],
        "D_os_median": os_["median"],
        "D_os_p90": os_["p90"],
        "D_os_top5_share": os_["top5_share"],
        "D_so_cell": by_cell_so,
        "D_so_area": by_area_so,
        "D_os_cell": by_cell_os,
        "D_os_area": by_area_os,
        "L_ref": float(length_scale_m),
        "L_cap": float(saturation_cap_m),
        "n_seepage": float(int(seepage_support.sum())),
        "n_network_sim": float(so["n_support"]),
        "n_network_obs": float(os_["n_support"]),
        "n_valid": float(counts_valid),
        "n_excess": float(counts_excess),
        "n_missing": float(counts_missing),
        "n_unreachable_so": so["n_unreachable"],
        "n_unreachable_os": os_["n_unreachable"],
        "frac_unreachable_so": frac_unreachable_so,
        "frac_unreachable_os": frac_unreachable_os,
        "beta_sim_continuity": simulated.continuity,
        "zero_fraction_so": so["zero_fraction"],
        "zero_fraction_os": os_["zero_fraction"],
        "frac_outlet_terminated": frac_outlet,
        "n_outlet_sealed": float(0.0 if observed_mask[outlet] else 1.0),
    }
    return SeepageDistanceResult(
        cost=abs(signed_gap),
        signed_gap=signed_gap,
        optimal_distance=optimal,
        status=status,
        components=components,
    )


__all__ = (
    "DISTANCE_METHOD",
    "SeepageDistanceResult",
    "Weighting",
    "seepage_distance_cost",
)
