"""Natural-observation helpers for network/discharge calibration.

The natural package mirrors the B0 truth-package file layout where possible so
existing B0 diagnostics can be reused. The scoring contract is different for
the network term: observed hydrography provides a presence/location target, not
per-cell drainage fluxes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.network import (
    equivalent_network_length,
    positive_outflow,
)
from hydromodpy.calibration.observations.network_transient_truth import (
    CandidateScore,
)
from hydromodpy.core.metrics import log_nse


@dataclass(frozen=True, slots=True)
class NaturalObservationPackageSummary:
    """Compact summary returned after writing a natural observation package."""

    output_dir: Path
    qbar_obs: float
    l_obs: float
    n_cells: int
    n_timesteps: int
    n_observed_network_active: int


@dataclass(frozen=True, slots=True)
class NaturalNetworkCost:
    """Natural network support/location cost and diagnostics."""

    total: float
    components: Mapping[str, float]


def natural_network_cost(
    candidate_steady_drain_by_cell: object,
    observed_network_mask: object,
    observed_network_distance_by_cell: object,
    centroids: object,
    cell_area: object,
    *,
    d_tol: float,
    threshold: float = 0.0,
    eta_dist: float = 1.0,
    empty_distance_penalty: float | None = None,
) -> NaturalNetworkCost:
    """Score simulated permanent drainage against observed hydrography.

    The distance term is ``abs(D_sim / D_obs - 1)``. ``D_sim`` is the
    area-weighted mean distance from simulated active drainage cells to the
    observed hydrographic network, and ``D_obs`` is the same distance statistic
    for observed-network cells. Flux mismatch and length penalties are
    deliberately omitted for natural hydrography observations.
    """

    sim = positive_outflow(candidate_steady_drain_by_cell)
    obs_mask = np.asarray(observed_network_mask, dtype=bool).reshape(-1)
    if sim.size != obs_mask.size:
        raise ValueError(
            "candidate_steady_drain_by_cell and observed_network_mask must have "
            f"the same length ({sim.size} != {obs_mask.size})."
        )
    if not np.any(obs_mask):
        raise ValueError("Observed network mask is empty.")

    centroids_arr = np.asarray(centroids, dtype=float)
    if centroids_arr.shape != (obs_mask.size, 2):
        raise ValueError("centroids must have shape (n_cells, 2) matching observed_network_mask.")
    area = np.asarray(cell_area, dtype=float).reshape(-1)
    if area.size != obs_mask.size:
        raise ValueError(f"cell_area length must match mask ({area.size} != {obs_mask.size}).")
    valid_area = np.where(np.isfinite(area) & (area > 0.0), area, 0.0)
    distance = np.asarray(observed_network_distance_by_cell, dtype=float).reshape(-1)
    if distance.size != obs_mask.size:
        raise ValueError(
            "observed_network_distance_by_cell length must match mask "
            f"({distance.size} != {obs_mask.size})."
        )
    if np.any(~np.isfinite(distance)) or np.any(distance < 0.0):
        raise ValueError("observed_network_distance_by_cell must be finite and >= 0.")

    width = float(d_tol)
    if not np.isfinite(width) or width <= 0.0:
        raise ValueError("d_tol must be finite and > 0.")
    eta_dist_value = float(eta_dist)
    if not np.isfinite(eta_dist_value) or eta_dist_value <= 0.0:
        raise ValueError("eta_dist must be finite and > 0.")

    sim_mask = sim > float(threshold)
    obs_distance_mean = _area_weighted_mean(distance, obs_mask, valid_area)
    if not np.any(sim_mask):
        dist_error = 10.0 if empty_distance_penalty is None else float(empty_distance_penalty)
        if not np.isfinite(dist_error) or dist_error < 0.0:
            raise ValueError("empty_distance_penalty must be finite and >= 0.")
        sim_distance_mean = float("nan")
        distance_ratio = float("nan")
        ratio_defined = 0.0
    else:
        sim_distance_mean = _area_weighted_mean(distance, sim_mask, valid_area)
        distance_ratio, dist_error, ratio_defined = _distance_ratio_cost(
            sim_distance_mean,
            obs_distance_mean,
            d_tol=width,
            undefined_penalty=empty_distance_penalty,
        )
    dist_cost = dist_error / eta_dist_value
    total = float(dist_cost)

    obs_length = equivalent_network_length(obs_mask, valid_area, d_tol=width)
    sim_length = equivalent_network_length(sim_mask, valid_area, d_tol=width)
    return NaturalNetworkCost(
        total=total,
        components={
            "E_dist": float(dist_error),
            "E_dist_ratio_abs_minus_one": float(dist_error),
            "C_dist": float(dist_cost),
            "D_sim_to_obs": float(sim_distance_mean),
            "D_obs_to_obs": float(obs_distance_mean),
            "distance_ratio": float(distance_ratio),
            "distance_ratio_defined": float(ratio_defined),
            "Q_ref_steady": float(np.count_nonzero(obs_mask)),
            "L_obs": float(obs_length),
            "L_sim": float(sim_length),
            "n_obs_active": float(np.count_nonzero(obs_mask)),
            "n_sim_active": float(np.count_nonzero(sim_mask)),
        },
    )


def discharge_log_nse_cost(
    q_sim: object,
    q_obs: object,
    *,
    eps: float | None = None,
) -> tuple[float, Mapping[str, float]]:
    """Return ``1 - NSElog`` and diagnostics for observed discharge."""

    sim = np.asarray(q_sim, dtype=float).reshape(-1)
    obs = np.asarray(q_obs, dtype=float).reshape(-1)
    if sim.size != obs.size:
        raise ValueError(f"q_sim and q_obs must have the same length ({sim.size} != {obs.size}).")
    finite = np.isfinite(sim) & np.isfinite(obs)
    if not np.any(finite):
        raise ValueError("q_sim and q_obs have no overlapping finite value.")
    effective_eps = _resolve_log_nse_epsilon(obs[finite], eps)
    score = float(log_nse(sim[finite], obs[finite], eps=effective_eps))
    if not np.isfinite(score):
        raise ValueError("NSElog is not finite for the observed discharge window.")
    cost = float(1.0 - score)
    return cost, {
        "NSElog": score,
        "C_NSElog": cost,
        "n_q_scored": float(np.count_nonzero(finite)),
        "nse_log_epsilon": effective_eps,
    }


def write_natural_observation_package(
    output_dir: str | Path,
    *,
    observed_q_total_release: object,
    observed_network_mask: object,
    observed_network_distance_by_cell: object,
    centroids: object,
    cell_area: object,
    time_index: Sequence[Any] | pd.DatetimeIndex | None = None,
    metadata: Mapping[str, Any] | None = None,
    tau_network: float = 0.0,
    d_tol: float | None = None,
    eta_dist: float = 1.0,
    alpha_q: float = 0.10,
    nse_log_epsilon: float | None = None,
    w_network: float = 0.3,
    w_discharge: float = 0.7,
    warmup_periods: int = 0,
    scored_periods: int | None = None,
) -> NaturalObservationPackageSummary:
    """Write a natural observation package with B0-compatible aliases."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    q_obs = np.asarray(observed_q_total_release, dtype=float).reshape(-1)
    if q_obs.size == 0:
        raise ValueError("observed_q_total_release must not be empty.")
    obs_mask = np.asarray(observed_network_mask, dtype=bool).reshape(-1)
    if not np.any(obs_mask):
        raise ValueError("observed_network_mask must contain at least one active cell.")
    centroids_arr = np.asarray(centroids, dtype=float)
    cell_area_arr = np.asarray(cell_area, dtype=float).reshape(-1)
    distance_arr = np.asarray(observed_network_distance_by_cell, dtype=float).reshape(-1)
    if centroids_arr.shape != (obs_mask.size, 2):
        raise ValueError("centroids must have shape (n_cells, 2) matching observed_network_mask.")
    if cell_area_arr.size != obs_mask.size:
        raise ValueError("cell_area length must match observed_network_mask.")
    if distance_arr.size != obs_mask.size:
        raise ValueError(
            "observed_network_distance_by_cell length must match observed_network_mask."
        )
    if np.any(~np.isfinite(distance_arr)) or np.any(distance_arr < 0.0):
        raise ValueError("observed_network_distance_by_cell must be finite and >= 0.")

    d_tol_value = _resolve_d_tol(cell_area_arr, d_tol)
    score_start, score_stop = _score_window(
        q_obs.size,
        warmup_periods=warmup_periods,
        scored_periods=scored_periods,
    )
    finite_q = q_obs[score_start:score_stop][np.isfinite(q_obs[score_start:score_stop])]
    if finite_q.size == 0:
        raise ValueError("The scored observed discharge window has no finite value.")
    qbar_obs = float(np.mean(finite_q))
    if not np.isfinite(qbar_obs) or qbar_obs <= 0.0:
        raise ValueError("Observed discharge mean must be finite and > 0.")
    l_obs = equivalent_network_length(obs_mask, cell_area_arr, d_tol=d_tol_value)

    if time_index is None:
        q_frame = pd.DataFrame(
            {
                "timestep": np.arange(q_obs.size, dtype=int),
                "q_total_release": q_obs,
            }
        )
    else:
        idx = pd.DatetimeIndex(time_index)
        if idx.size != q_obs.size:
            raise ValueError(f"time_index length must match q_obs ({idx.size} != {q_obs.size}).")
        q_frame = pd.DataFrame({"datetime": idx.astype(str), "q_total_release": q_obs})

    normalization = {
        "contract_version": "natural_network_steady_discharge_transient.v1",
        "tau_network": float(tau_network),
        "Q_ref_steady": float(np.count_nonzero(obs_mask)),
        "Qbar_ref": qbar_obs,
        "L_ref": float(l_obs),
        "d_tol": float(d_tol_value),
        "eta_dist": float(eta_dist),
        "network_distance_metric": "abs_sim_to_obs_over_obs_to_obs_distance_ratio_minus_one",
        "discharge_metric": "nse_log",
        "alpha_Q": float(alpha_q),
        "nse_log_epsilon": nse_log_epsilon,
        "w_reseau": float(w_network),
        "w_debit": float(w_discharge),
        "warmup_periods": int(score_start),
        "score_start_index": int(score_start),
        "score_stop_index": int(score_stop),
        "scored_periods": int(score_stop - score_start),
    }
    metadata_out = dict(metadata or {})
    metadata_out.setdefault("package_type", "natural_observation_package")
    metadata_out.setdefault("generated_at", datetime.now(UTC).isoformat())
    metadata_out.setdefault("n_cells", int(obs_mask.size))
    metadata_out.setdefault("n_timesteps", int(q_obs.size))
    metadata_out.setdefault(
        "network_observable",
        "observed_hydrography_presence_and_distance_ratio",
    )
    metadata_out.setdefault("discharge_observable", "observed_streamflow_nse_log")

    pseudo_ref = obs_mask.astype("float64")
    np.savez_compressed(out_dir / "observed_network_active_mask.npz", active_mask=obs_mask)
    np.savez_compressed(
        out_dir / "observed_network_distance_by_cell.npz",
        distance_to_network=distance_arr,
    )
    np.savez_compressed(out_dir / "steady_network_active_mask.npz", active_mask=obs_mask)
    np.savez_compressed(out_dir / "steady_network_drain_by_cell.npz", outflow_drain=pseudo_ref)
    np.savez_compressed(
        out_dir / "cell_geometry.npz", centroids=centroids_arr, cell_area=cell_area_arr
    )
    q_frame.to_csv(out_dir / "observed_q_total_release.csv", index=False)
    q_frame.to_csv(out_dir / "transient_q_total_release.csv", index=False)
    _write_json(out_dir / "normalization.json", normalization)
    _write_json(out_dir / "metadata.json", metadata_out)

    return NaturalObservationPackageSummary(
        output_dir=out_dir,
        qbar_obs=qbar_obs,
        l_obs=float(l_obs),
        n_cells=int(obs_mask.size),
        n_timesteps=int(q_obs.size),
        n_observed_network_active=int(np.count_nonzero(obs_mask)),
    )


def score_natural_network_transient_candidate(
    observation_dir: str | Path,
    *,
    candidate_steady_drain_by_cell: object,
    candidate_q_total_release: object,
) -> CandidateScore:
    """Score one candidate against a written natural observation package."""

    obs_path = Path(observation_dir)
    normalization = _read_json(obs_path / "normalization.json")
    obs_mask = _load_npz_array(obs_path / "observed_network_active_mask.npz", "active_mask")
    obs_distance = _load_npz_array(
        obs_path / "observed_network_distance_by_cell.npz",
        "distance_to_network",
    )
    with np.load(obs_path / "cell_geometry.npz") as geometry:
        centroids = np.asarray(geometry["centroids"], dtype=float)
        cell_area = np.asarray(geometry["cell_area"], dtype=float)
    q_obs = pd.read_csv(obs_path / "observed_q_total_release.csv")["q_total_release"].to_numpy(
        dtype=float
    )

    network = natural_network_cost(
        candidate_steady_drain_by_cell,
        obs_mask,
        obs_distance,
        centroids,
        cell_area,
        d_tol=float(normalization["d_tol"]),
        threshold=float(normalization["tau_network"]),
        eta_dist=float(normalization["eta_dist"]),
    )

    start = int(normalization["score_start_index"])
    stop = int(normalization["score_stop_index"])
    q_sim = np.asarray(candidate_q_total_release, dtype=float).reshape(-1)
    if q_sim.size != q_obs.size:
        raise ValueError(
            f"candidate_q_total_release length must be {q_obs.size}, got {q_sim.size}."
        )
    eps_raw = normalization.get("nse_log_epsilon")
    eps = None if eps_raw is None else float(eps_raw)
    discharge_cost, discharge_components = discharge_log_nse_cost(
        q_sim[start:stop],
        q_obs[start:stop],
        eps=eps,
    )

    w_network = float(normalization["w_reseau"])
    w_discharge = float(normalization["w_debit"])
    weight_sum = w_network + w_discharge
    if not np.isfinite(weight_sum) or weight_sum <= 0.0:
        raise ValueError("w_reseau + w_debit must be finite and > 0.")
    w_network /= weight_sum
    w_discharge /= weight_sum
    total = float(w_network * network.total + w_discharge * discharge_cost)

    components = {
        "J": total,
        "C_reseau_naturel": float(network.total),
        "C_debit_obs": float(discharge_cost),
        "w_reseau": w_network,
        "w_debit": w_discharge,
    }
    components.update({f"network.{key}": float(value) for key, value in network.components.items()})
    components.update(
        {f"discharge.{key}": float(value) for key, value in discharge_components.items()}
    )
    return CandidateScore(total=total, components=components)


def _resolve_d_tol(cell_area: np.ndarray, d_tol: float | None) -> float:
    if d_tol is not None:
        value = float(d_tol)
    else:
        valid_area = cell_area[np.isfinite(cell_area) & (cell_area > 0.0)]
        if valid_area.size == 0:
            raise ValueError("Cannot infer d_tol without positive cell areas.")
        value = float(np.sqrt(np.nanmedian(valid_area)))
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError("d_tol must be finite and > 0.")
    return value


def _area_weighted_mean(values: np.ndarray, mask: np.ndarray, area: np.ndarray) -> float:
    weights = np.where(mask, area, 0.0)
    total = float(np.sum(weights))
    if total <= 0.0:
        return float(np.nanmean(values[mask]))
    return float(np.sum(np.asarray(values, dtype=float) * weights) / total)


def _distance_ratio_cost(
    sim_distance_mean: float,
    obs_distance_mean: float,
    *,
    d_tol: float,
    undefined_penalty: float | None,
) -> tuple[float, float, float]:
    sim_value = float(sim_distance_mean)
    obs_value = float(obs_distance_mean)
    if sim_value == 0.0 and obs_value == 0.0:
        return 1.0, 0.0, 1.0
    if obs_value > 0.0:
        ratio = float(sim_value / obs_value)
        return ratio, float(abs(ratio - 1.0)), 1.0
    if undefined_penalty is not None:
        penalty = float(undefined_penalty)
    else:
        penalty = sim_value / float(d_tol)
    if not np.isfinite(penalty) or penalty < 0.0:
        raise ValueError("undefined distance-ratio penalty must be finite and >= 0.")
    return float("nan"), float(penalty), 0.0


def _resolve_log_nse_epsilon(obs: np.ndarray, eps: float | None) -> float:
    if eps is not None:
        value = float(eps)
        if not np.isfinite(value) or value < 0.0:
            raise ValueError("nse_log_epsilon must be finite and >= 0.")
        return value
    positives = obs[obs > 0.0]
    median = float(np.median(positives)) if positives.size else 1.0
    return max(1.0e-9, 0.01 * median)


def _score_window(
    n_values: int,
    *,
    warmup_periods: int,
    scored_periods: int | None,
) -> tuple[int, int]:
    start = int(warmup_periods)
    if start < 0 or start >= n_values:
        raise ValueError("warmup_periods must point inside observed_q_total_release.")
    stop = n_values if scored_periods is None else start + int(scored_periods)
    if stop <= start or stop > n_values:
        raise ValueError("scored_periods defines an invalid scoring window.")
    return start, stop


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_npz_array(path: Path, key: str) -> np.ndarray:
    with np.load(path) as data:
        return np.asarray(data[key])


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


__all__ = [
    "NaturalNetworkCost",
    "NaturalObservationPackageSummary",
    "discharge_log_nse_cost",
    "natural_network_cost",
    "score_natural_network_transient_candidate",
    "write_natural_observation_package",
]
