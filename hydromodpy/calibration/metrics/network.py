"""Physical network metrics for calibration prototypes.

The helpers in this module are intentionally solver-agnostic. They score a
cell-based drainage network from positive per-cell outflow, cell centroids and
cell areas. This keeps the first network/discharge calibration prototype out of
the global calibration schema until the contract is stable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree


@dataclass(frozen=True, slots=True)
class NetworkCost:
    """Composite network cost and diagnostic components."""

    total: float
    components: Mapping[str, float]


def positive_outflow(values: object) -> np.ndarray:
    """Return a flat finite positive-outflow vector.

    Negative and nodata-like values are treated as no outflow. This function
    expects the caller to provide already sign-corrected outflow where possible;
    it only enforces the B0 convention used by the metric: active drainage is
    strictly positive.
    """

    out = np.asarray(values, dtype=float).reshape(-1)
    finite = np.isfinite(out) & (out > -9000.0)
    return np.where(finite, np.maximum(out, 0.0), 0.0).astype("float64", copy=False)


def active_network_mask(values: object, *, threshold: float = 0.0) -> np.ndarray:
    """Return ``True`` where positive outflow exceeds ``threshold``."""

    return positive_outflow(values) > float(threshold)


def _as_float_vector(values: object, *, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty.")
    return arr


def _as_centroids(values: object, *, expected_size: int) -> np.ndarray:
    centroids = np.asarray(values, dtype=float)
    if centroids.ndim != 2 or centroids.shape[1] != 2:
        raise ValueError("centroids must have shape (n_cells, 2).")
    if centroids.shape[0] != expected_size:
        raise ValueError(
            "centroids length must match drainage vectors "
            f"({centroids.shape[0]} != {expected_size})."
        )
    if not np.all(np.isfinite(centroids)):
        raise ValueError("centroids must be finite.")
    return centroids


def _reject_binary_reference(d_ref: np.ndarray, *, name: str) -> None:
    """Refuse a 0/1 mask where a per-cell drainage outflow is required.

    A mask normalizes the flux error by a count of cells instead of a
    discharge, which yields a plausible-looking but meaningless score.
    """

    active = int(np.count_nonzero(d_ref))
    if active == 0 or not np.all((d_ref == 0.0) | (d_ref == 1.0)):
        return
    raise ValueError(
        f"{name} is a binary 0/1 mask ({d_ref.size} cells, {active} active, "
        f"sum = {float(np.sum(d_ref))}), but a per-cell drainage outflow is "
        "required: normalizing by the sum of a mask divides a flux by a count "
        "of cells. Pass the reference outflow field, not its active mask."
    )


def _reference_outflow(
    d_ref: np.ndarray,
    q_ref_steady: float | None,
) -> float:
    if q_ref_steady is None:
        q_ref = float(np.sum(d_ref))
    else:
        q_ref = float(q_ref_steady)
    if not np.isfinite(q_ref) or q_ref <= 0.0:
        raise ValueError("q_ref_steady must be finite and > 0.")
    return q_ref


def nearest_distances_to_mask(
    centroids: object,
    mask: object,
) -> np.ndarray:
    """Return distance from every centroid to the nearest active mask cell."""

    mask_arr = np.asarray(mask, dtype=bool).reshape(-1)
    centroids_arr = _as_centroids(centroids, expected_size=mask_arr.size)
    if not np.any(mask_arr):
        raise ValueError("Cannot compute distances to an empty network mask.")
    tree = cKDTree(centroids_arr[mask_arr])
    distances, _ = tree.query(centroids_arr)
    return np.asarray(distances, dtype="float64")


def equivalent_network_length(
    mask: object,
    cell_area: object,
    *,
    d_tol: float,
) -> float:
    """Return the cell-network length equivalent ``sum(area) / d_tol``."""

    width = float(d_tol)
    if not np.isfinite(width) or width <= 0.0:
        raise ValueError("d_tol must be finite and > 0.")
    mask_arr = np.asarray(mask, dtype=bool).reshape(-1)
    area = _as_float_vector(cell_area, name="cell_area")
    if area.size != mask_arr.size:
        raise ValueError(f"cell_area length must match mask ({area.size} != {mask_arr.size}).")
    valid_area = np.where(np.isfinite(area) & (area > 0.0), area, 0.0)
    return float(np.sum(valid_area[mask_arr]) / width)


def network_flux_error(
    d_sim: object,
    d_ref: object,
    *,
    q_ref_steady: float | None = None,
) -> float:
    """Return the normalized L1 error in per-cell drainage outflow."""

    sim = positive_outflow(d_sim)
    ref = positive_outflow(d_ref)
    if sim.size != ref.size:
        raise ValueError(f"d_sim and d_ref must have the same length ({sim.size} != {ref.size}).")
    _reject_binary_reference(ref, name="d_ref")
    q_ref = _reference_outflow(ref, q_ref_steady)
    return float(np.sum(np.abs(sim - ref)) / q_ref)


def network_distance_error(
    d_sim: object,
    d_ref: object,
    centroids: object,
    *,
    d_tol: float,
    q_ref_steady: float | None = None,
    threshold: float = 0.0,
    empty_distance_penalty: float | None = None,
) -> float:
    """Return the outflow-weighted placement error.

    The score is dimensionless. A value near 1 means that, on average, drainage
    is displaced by one ``d_tol`` corridor. If the simulated network is empty,
    a finite penalty is returned so robust optimizers can keep progressing.
    """

    width = float(d_tol)
    if not np.isfinite(width) or width <= 0.0:
        raise ValueError("d_tol must be finite and > 0.")
    sim = positive_outflow(d_sim)
    ref = positive_outflow(d_ref)
    if sim.size != ref.size:
        raise ValueError(f"d_sim and d_ref must have the same length ({sim.size} != {ref.size}).")
    q_ref = _reference_outflow(ref, q_ref_steady)
    centroids_arr = _as_centroids(centroids, expected_size=ref.size)

    ref_mask = ref > float(threshold)
    sim_mask = sim > float(threshold)
    if not np.any(ref_mask):
        raise ValueError("Reference network is empty.")

    dist_to_ref = nearest_distances_to_mask(centroids_arr, ref_mask)
    if not np.any(sim_mask):
        if empty_distance_penalty is not None:
            penalty = float(empty_distance_penalty)
            if not np.isfinite(penalty) or penalty < 0.0:
                raise ValueError("empty_distance_penalty must be finite and >= 0.")
            return penalty
        return float(np.mean(dist_to_ref) / width)

    dist_to_sim = nearest_distances_to_mask(centroids_arr, sim_mask)
    numerator = float(np.sum(sim * dist_to_ref) + np.sum(ref * dist_to_sim))
    return numerator / (2.0 * width * q_ref)


def network_length_error(
    mask_sim: object,
    mask_ref: object,
    cell_area: object,
    *,
    d_tol: float,
) -> float:
    """Return the relative error in active network equivalent length."""

    sim_length = equivalent_network_length(mask_sim, cell_area, d_tol=d_tol)
    ref_length = equivalent_network_length(mask_ref, cell_area, d_tol=d_tol)
    if not np.isfinite(ref_length) or ref_length <= 0.0:
        raise ValueError("Reference network length must be finite and > 0.")
    return float(abs(sim_length - ref_length) / ref_length)


def network_cost(
    d_sim: object,
    d_ref: object,
    centroids: object,
    cell_area: object,
    *,
    d_tol: float,
    q_ref_steady: float | None = None,
    threshold: float = 0.0,
    eta_flux: float = 0.05,
    eta_dist: float = 1.0,
    eta_len: float = 0.10,
    weight_flux: float = 0.4,
    weight_dist: float = 0.4,
    weight_len: float = 0.2,
    empty_distance_penalty: float | None = None,
) -> NetworkCost:
    """Return the B0 physical network cost.

    The total is a weighted sum of normalized flux, distance and length costs.
    Weights are normalized internally, so callers can pass either fractions or
    positive relative weights.
    """

    sim = positive_outflow(d_sim)
    ref = positive_outflow(d_ref)
    if sim.size != ref.size:
        raise ValueError(f"d_sim and d_ref must have the same length ({sim.size} != {ref.size}).")

    _reject_binary_reference(ref, name="d_ref")
    q_ref = _reference_outflow(ref, q_ref_steady)
    centroids_arr = _as_centroids(centroids, expected_size=ref.size)
    cell_area_arr = _as_float_vector(cell_area, name="cell_area")
    if cell_area_arr.size != ref.size:
        raise ValueError(
            f"cell_area length must match drainage vectors ({cell_area_arr.size} != {ref.size})."
        )

    tolerances = np.asarray([eta_flux, eta_dist, eta_len], dtype=float)
    if np.any(~np.isfinite(tolerances)) or np.any(tolerances <= 0.0):
        raise ValueError("eta_flux, eta_dist and eta_len must be finite and > 0.")
    weights = np.asarray([weight_flux, weight_dist, weight_len], dtype=float)
    if np.any(~np.isfinite(weights)) or np.any(weights < 0.0) or float(weights.sum()) <= 0.0:
        raise ValueError("At least one finite non-negative component weight is required.")
    weights = weights / float(weights.sum())

    sim_mask = sim > float(threshold)
    ref_mask = ref > float(threshold)
    if not np.any(ref_mask):
        raise ValueError("Reference network is empty.")

    flux_error = network_flux_error(sim, ref, q_ref_steady=q_ref)
    dist_error = network_distance_error(
        sim,
        ref,
        centroids_arr,
        d_tol=d_tol,
        q_ref_steady=q_ref,
        threshold=threshold,
        empty_distance_penalty=empty_distance_penalty,
    )
    len_error = network_length_error(sim_mask, ref_mask, cell_area_arr, d_tol=d_tol)

    flux_cost = flux_error / float(eta_flux)
    dist_cost = dist_error / float(eta_dist)
    len_cost = len_error / float(eta_len)
    total = float(np.dot(weights, np.asarray([flux_cost, dist_cost, len_cost], dtype=float)))

    sim_length = equivalent_network_length(sim_mask, cell_area_arr, d_tol=d_tol)
    ref_length = equivalent_network_length(ref_mask, cell_area_arr, d_tol=d_tol)
    components = {
        "E_flux": float(flux_error),
        "E_dist": float(dist_error),
        "E_len": float(len_error),
        "C_flux": float(flux_cost),
        "C_dist": float(dist_cost),
        "C_len": float(len_cost),
        "weight_flux": float(weights[0]),
        "weight_dist": float(weights[1]),
        "weight_len": float(weights[2]),
        "Q_ref_steady": float(q_ref),
        "L_ref": float(ref_length),
        "L_sim": float(sim_length),
        "n_ref_active": float(np.count_nonzero(ref_mask)),
        "n_sim_active": float(np.count_nonzero(sim_mask)),
    }
    return NetworkCost(total=total, components=components)


__all__ = [
    "NetworkCost",
    "active_network_mask",
    "equivalent_network_length",
    "nearest_distances_to_mask",
    "network_cost",
    "network_distance_error",
    "network_flux_error",
    "network_length_error",
    "positive_outflow",
]
