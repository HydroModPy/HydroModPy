"""The signed gap between an excess of simulated stream and a missing one.

For every cell where the model releases water, trace the descent to the mapped
stream network and measure it; average over the simulated network to get
``D_so``. Reciprocally, from every mapped cell, the descent to the simulated
network averages to ``D_os``. The criterion is

    J_signed = D_so - D_os        the residual a root search drives to zero
    J        = abs(J_signed)      the cost, Eq. 1 of the paper
    Doptim   = (D_so + D_os) / 2  Eq. 2, a diagnostic and never the cost
    roptim   = Doptim / h_obs     Eq. 3, the validity indicator
    Doptim  <= validity_length    Eq. 4, the validity bound, in metres

``roptim`` is the paper's ratio, published for comparison with its Table 1.
The bound is a length (:func:`hydromodpy.core.stream_geometry.
resolve_validity_length`): two cells ``2 h_obs`` by default, the paper's
``roptim <= 2``, widened by a declared positional accuracy or by the snap
floor, or set by the output.

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

Secondary diagnostics travel in the components and never reach the cost, see
:func:`secondary_diagnostics`: the ratio ``D_so / D_os`` and the overlap indices
of the authors' published code.

With a minimal and a maximal map, each bound is this same cost evaluated once,
on its own mask against its own map. Its components carry the suffix
``_minimal`` or ``_maximal`` and its pair the bound's weight
(:func:`weighted_pair`); the criterion sums the weighted gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from hydromodpy.core.stream_geometry import (
    CriterionSupports,
    NetworkGeometry,
    ValidityLength,
    criterion_supports,
)
from hydromodpy.core.stream_network import SimulatedNetwork
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
    """The signed residual and everything needed to read it.

    ``J`` and ``Doptim`` live in ``components`` beside the thirty other
    quantities one trial produces, and are read from there.
    """

    signed_gap: float
    """``J_signed``. It travels in the components, never in the cost, so that
    picking the best trial by lowest cost gives the trial closest to zero and
    not the most negative one."""

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


def _ratio(numerator: float, denominator: float) -> float:
    """Return ``numerator / denominator``, NaN when either is not a usable number."""
    if not (np.isfinite(numerator) and np.isfinite(denominator)) or denominator == 0.0:
        return float("nan")
    return float(numerator / denominator)


def secondary_diagnostics(
    *,
    d_so: float,
    d_os: float,
    supports: CriterionSupports,
    cell_area_m2: np.ndarray,
) -> dict[str, float]:
    """Return the diagnostics other codes of the method recorded, never the cost.

    ``D_so_over_D_os`` is the ratio the v1 example 10 recorded as ``DSO/DOS``
    and the authors' dichotomy branched on as ``Sflow/Oflow`` (Zenodo 8311547,
    ``launch_dichotomy.py``). Its crossing of one is the zero of ``J_signed``,
    so it adds no information to the bracket, only a scale-free reading.

    The rest reproduces ``store_dataframe.fuzzy`` and ``total_length`` of the
    same code (``objective_function.py``), which classify the cells of the
    basin into four classes and score them:

    - ``n_neither``: ``Nc``, neither simulated nor mapped. ``Sc``, ``Si``,
      ``Ni``, ``So``, ``Sm`` are already published as ``n_valid``,
      ``n_excess``, ``n_missing``, ``n_network_obs`` and ``n_network_sim``.
    - ``overlap_Ea = 1 - |Sm - So| / So``: agreement of the network sizes.
    - ``overlap_Sa = 1 - Si / So``: excess of simulated stream, relative to
      the mapped size.
    - ``overlap_Na = 1 - Ni / No``: missing stream, relative to the cells the
      map leaves without one, ``No = Sc + Si + Ni + Nc - So``.
    - ``overlap_E = Ea * Sa * Na``.
    - ``L_sim_m``, ``L_obs_m``: the length of each network.

    Departures from the raster version. The cells are the criterion's own
    supports, inside the catchment and without the water bodies, where the
    published code counted every pixel of the basin. The mapped side is the
    raw network, as ``D_os`` reads it; the published code counted the mapped
    network after tracing it downslope. A length is the sum of the cell sizes,
    ``sqrt(area)``, over the network, where the published code summed the
    polylines WhiteboxTools vectorised through pixel centres and dropped the
    stubs of at most two cells and 110 m: a diagonal reach therefore reads
    ``sqrt(2)`` shorter here, on both networks alike, and the stubs stay in.
    """
    keep = supports.keep
    so = float(supports.support_os.sum())
    sm = float(supports.support_so.sum())
    si = float(supports.excess.sum())
    ni = float(supports.missing.sum())
    nc = float((keep & ~supports.support_so & ~supports.support_os).sum())
    no = float(keep.sum()) - so
    ea = 1.0 - _ratio(abs(sm - so), so)
    sa = 1.0 - _ratio(si, so)
    na = 1.0 - _ratio(ni, no)
    size = np.sqrt(np.asarray(cell_area_m2, dtype=float).reshape(-1))
    return {
        "D_so_over_D_os": _ratio(d_so, d_os),
        "n_neither": nc,
        "overlap_Ea": ea,
        "overlap_Sa": sa,
        "overlap_Na": na,
        "overlap_E": ea * sa * na,
        "L_sim_m": float(size[supports.support_so].sum()),
        "L_obs_m": float(size[supports.support_os].sum()),
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
    validity: ValidityLength | None = None,
) -> SeepageDistanceResult:
    """Evaluate the signed gap for one trial.

    ``length_scale_m`` is ``h_obs``, the divisor of ``roptim`` (Eq. 3).
    ``validity`` is the length ``Doptim`` is bounded by (Eq. 4); None is
    ``2 * length_scale_m``, the paper's two cells. Each trial publishes
    ``roptim_valid``, ``validity_length_m`` and the provenance code
    ``validity_length_provenance``; the runner reads them once, at the trial
    the search returns.

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
    supports = criterion_supports(
        simulated=simulated,
        observed=observed_mask,
        catchment=catchment_mask,
        active=active,
        excluded=excluded,
    )
    support_so = supports.support_so
    support_os = supports.support_os
    if not np.any(support_os):
        # Say WHICH of the three intersections emptied it: a CRS mismatch, a
        # catchment that closed on the wrong cell and a mesh whose active domain
        # misses the streams all produce the same empty support otherwise.
        raise ValueError(
            "the observed stream network holds no cell inside the catchment. "
            f"{int(observed_mask.sum())} mapped cell(s) on the mesh, "
            f"{int(active.sum())} active cell(s), "
            f"{int(catchment_mask.sum())} in the catchment, "
            f"{int((observed_mask & catchment_mask).sum())} mapped inside it, "
            f"{int(support_os.sum())} left after the exclusions. "
            "Check the CRS of the network, and the outlet the catchment closed on."
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
    if status == "ok" and frac_unreachable_so > float(max_unreachable_fraction):
        # The bound guards ONE direction: D_so, whose target is the mapped
        # network with the outlet sealed into it. That target does not move
        # between trials, and every cell of a conditioned catchment reaches it,
        # so anything beyond a few per cent means the surface is not conditioned
        # and the number would be a fiction. This is the direction the 0.03 to
        # 2.5 per cent of the specification was measured on.
        #
        # D_os is NOT guarded. Its target is the SIMULATED network, which is
        # what the calibration moves: a high K retracts the simulated network
        # into the talwegs, and mapped cells then legitimately have nothing to
        # descend into. That is not a broken surface, it is the measurement
        # saying the model has no stream there, and it is the very signal the
        # search reads at the high end of its bracket. Those cells saturate at
        # the basin's longest descent, the policy section 3.6 chose over
        # counting +inf and over dropping them from the support.
        status = "failed"

    roptim = optimal / float(length_scale_m) if np.isfinite(optimal) else float("nan")
    bound = validity or ValidityLength(2.0 * float(length_scale_m), "auto")
    within = bool(np.isfinite(optimal) and optimal <= bound.length_m)

    # Share of the simulated support whose descent meets the target only at the
    # sealed outlet: it says how much of D_so rests on that one added cell.
    outlet_only = np.isinf(distance_to_observed_raw) & support_so
    frac_outlet = float(outlet_only.sum() / n_support_so)

    d_so_seepage_only = mean_downslope_distance(
        distance_to_observed,
        supports.seepage,
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
        "roptim_valid": float(within),
        "validity_length_m": float(bound.length_m),
        "validity_length_provenance": bound.code,
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
        "n_seepage": float(int(supports.seepage.sum())),
        "n_network_sim": float(so["n_support"]),
        "n_network_obs": float(os_["n_support"]),
        **supports.counts,
        "n_unreachable_so": so["n_unreachable"],
        "n_unreachable_os": os_["n_unreachable"],
        "frac_unreachable_so": frac_unreachable_so,
        "frac_unreachable_os": frac_unreachable_os,
        "beta_sim_continuity": simulated.continuity,
        "zero_fraction_so": so["zero_fraction"],
        "zero_fraction_os": os_["zero_fraction"],
        "frac_outlet_terminated": frac_outlet,
        "n_outlet_sealed": float(0.0 if observed_mask[outlet] else 1.0),
        **secondary_diagnostics(d_so=d_so, d_os=d_os, supports=supports, cell_area_m2=cell_area_m2),
    }
    return SeepageDistanceResult(
        signed_gap=signed_gap,
        status=status,
        components=components,
    )


MINIMAL_SUFFIX = "_minimal"
"""Suffix of every component of the minimal (permanent) bound."""

MAXIMAL_SUFFIX = "_maximal"
"""Suffix of every component of the maximal (complete) bound."""

VALIDATION_SUFFIX = "_maximal_validation"
"""Suffix of the maximal map scored beside a one-state cost on the minimal map.

A distinct name on purpose: a search that finds ``J_signed_maximal`` reads a
bound in the cost, and this one never is."""


def score_on_geometry(
    simulated: SimulatedNetwork,
    geometry: NetworkGeometry,
    *,
    weighting: Weighting = "cell",
    max_unreachable_fraction: float = 0.05,
    validity_length_m: float | None = None,
) -> SeepageDistanceResult:
    """Score one simulated network against the map a geometry was built on.

    ``validity_length_m`` is the output's declared ``validity_length`` in
    metres, None for ``"auto"``, which the geometry resolves from its own
    ``h_obs``, declared accuracy and snap floor
    (:meth:`~hydromodpy.core.stream_geometry.NetworkGeometry.validity_length`).
    Each map resolves its own, so the two bounds of an output may differ.
    """
    return seepage_distance_cost(
        simulated=simulated,
        observed=geometry.observed,
        outlet=geometry.outlet,
        catchment=geometry.catchment,
        metric=geometry.metric,
        distance_to_observed=geometry.distance_to_observed,
        distance_to_observed_raw=geometry.distance_to_observed_raw,
        cell_area_m2=geometry.cell_area_m2,
        length_scale_m=geometry.h_obs_m,
        saturation_cap_m=geometry.saturation_cap_m,
        excluded=geometry.excluded,
        weighting=weighting,
        max_unreachable_fraction=max_unreachable_fraction,
        validity=geometry.validity_length(validity_length_m),
    )


def weighted_pair(scored: SeepageDistanceResult, weight: float = 1.0) -> list[float]:
    """Return ``weight * (D_so, D_os)``, the pair a block scores for one bound.

    ``D_so`` has no support when the network is empty, so it is rebuilt from
    ``D_os`` and the signed residual rather than read: that way the pair and
    the residual the bracket closes on cannot disagree. The weight multiplies
    both distances, so the criterion summing ``|D_so - D_os|`` over the pairs
    of a vector returns ``w_minimal |J_minimal| + w_maximal |J_maximal|``.
    """
    d_os = float(scored.components["D_os"])
    return [float(weight) * (d_os + float(scored.signed_gap)), float(weight) * d_os]


def with_suffix(components: dict[str, float], suffix: str) -> dict[str, float]:
    """Return the components renamed ``<key><suffix>``."""
    return {f"{key}{suffix}": float(value) for key, value in components.items()}


__all__ = (
    "DISTANCE_METHOD",
    "MAXIMAL_SUFFIX",
    "MINIMAL_SUFFIX",
    "VALIDATION_SUFFIX",
    "SeepageDistanceResult",
    "Weighting",
    "score_on_geometry",
    "secondary_diagnostics",
    "seepage_distance_cost",
    "weighted_pair",
    "with_suffix",
)
