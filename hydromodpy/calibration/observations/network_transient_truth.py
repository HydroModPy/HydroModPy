"""Truth-package helpers for network/transient calibration prototypes."""

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
    network_cost,
    positive_outflow,
)


@dataclass(frozen=True, slots=True)
class TruthPackageSummary:
    """Compact summary returned after writing a truth package."""

    output_dir: Path
    q_ref_steady: float
    qbar_ref: float
    l_ref: float
    n_cells: int
    n_timesteps: int
    n_ref_active: int


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Joint B0 candidate score with per-component diagnostics."""

    total: float
    components: Mapping[str, float]


def mesh_cell_geometry(
    vertices: object,
    face_node_connectivity: object,
) -> tuple[np.ndarray, np.ndarray]:
    """Return cell centroids and planar areas from UGRID-style mesh arrays."""

    points = np.asarray(vertices, dtype=float)
    faces = np.asarray(face_node_connectivity, dtype=int)
    if points.ndim != 2 or points.shape[1] < 2:
        raise ValueError("vertices must have shape (n_vertices, >=2).")
    if faces.ndim == 1:
        faces = faces.reshape(1, -1)
    if faces.ndim != 2:
        raise ValueError("face_node_connectivity must be a 2D array.")

    centroids = np.full((faces.shape[0], 2), np.nan, dtype="float64")
    area = np.full(faces.shape[0], np.nan, dtype="float64")
    for cell_id, row in enumerate(faces):
        node_ids = np.asarray(row, dtype=int)
        node_ids = node_ids[(node_ids >= 0) & (node_ids < points.shape[0])]
        if node_ids.size < 3:
            continue
        polygon = np.asarray(points[node_ids, :2], dtype=float)
        if not np.all(np.isfinite(polygon)):
            continue
        centroids[cell_id] = np.mean(polygon, axis=0)
        x = polygon[:, 0]
        y = polygon[:, 1]
        area[cell_id] = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))

    if not np.all(np.isfinite(centroids)):
        raise ValueError("Could not compute finite centroids for every mesh cell.")
    if not np.all(np.isfinite(area) & (area > 0.0)):
        raise ValueError("Could not compute positive area for every mesh cell.")
    return centroids, area


def q_total_release_from_drain_by_cell(drain_by_cell: object) -> np.ndarray:
    """Sum positive DRAIN release over all cells for every timestep."""

    values = np.asarray(drain_by_cell, dtype=float)
    if values.ndim == 0:
        values = values.reshape(1, 1)
    elif values.ndim == 1:
        values = values.reshape(1, -1)
    else:
        values = values.reshape(values.shape[0], -1)
    out = [float(np.sum(positive_outflow(row))) for row in values]
    return np.asarray(out, dtype="float64")


def discharge_rmse_cost(
    q_sim: object,
    q_ref: object,
    *,
    alpha_q: float,
    qbar_ref: float | None = None,
) -> tuple[float, Mapping[str, float]]:
    """Return ``RMSE_Q / (alpha_q * Qbar_ref)`` and diagnostics."""

    sim = np.asarray(q_sim, dtype=float).reshape(-1)
    ref = np.asarray(q_ref, dtype=float).reshape(-1)
    if sim.size != ref.size:
        raise ValueError(f"q_sim and q_ref must have the same length ({sim.size} != {ref.size}).")
    finite = np.isfinite(sim) & np.isfinite(ref)
    if not np.any(finite):
        raise ValueError("q_sim and q_ref have no overlapping finite value.")
    alpha = float(alpha_q)
    if not np.isfinite(alpha) or alpha <= 0.0:
        raise ValueError("alpha_q must be finite and > 0.")
    qbar = float(np.mean(ref[finite]) if qbar_ref is None else qbar_ref)
    if not np.isfinite(qbar) or qbar <= 0.0:
        raise ValueError("qbar_ref must be finite and > 0.")

    rmse = float(np.sqrt(np.mean((sim[finite] - ref[finite]) ** 2)))
    cost = rmse / (alpha * qbar)
    return cost, {
        "RMSE_Q": rmse,
        "RMSE_Q_over_Qbar_ref": rmse / qbar,
        "Qbar_ref": qbar,
        "alpha_Q": alpha,
        "n_q_scored": float(np.count_nonzero(finite)),
    }


def write_network_transient_truth_package(
    output_dir: str | Path,
    *,
    steady_drain_by_cell: object,
    transient_q_total_release: object,
    centroids: object,
    cell_area: object,
    time_index: Sequence[Any] | pd.DatetimeIndex | None = None,
    metadata: Mapping[str, Any] | None = None,
    tau_network: float = 0.0,
    d_tol: float | None = None,
    eta_flux: float = 0.05,
    eta_dist: float = 1.0,
    eta_len: float = 0.10,
    a_flux: float = 0.4,
    a_dist: float = 0.4,
    a_len: float = 0.2,
    alpha_q: float = 0.10,
    w_network: float = 0.5,
    w_discharge: float = 0.5,
    warmup_periods: int = 0,
    scored_periods: int | None = None,
) -> TruthPackageSummary:
    """Write the B0 truth package from already extracted arrays."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    d_ref = positive_outflow(steady_drain_by_cell)
    q_ref = np.asarray(transient_q_total_release, dtype=float).reshape(-1)
    centroids_arr = np.asarray(centroids, dtype=float)
    cell_area_arr = np.asarray(cell_area, dtype=float).reshape(-1)

    if centroids_arr.shape != (d_ref.size, 2):
        raise ValueError(
            "centroids must have shape (n_cells, 2) matching steady_drain_by_cell "
            f"({centroids_arr.shape} vs {d_ref.size})."
        )
    if cell_area_arr.size != d_ref.size:
        raise ValueError(
            f"cell_area length must match steady_drain_by_cell ({cell_area_arr.size} != {d_ref.size})."
        )
    if q_ref.size == 0:
        raise ValueError("transient_q_total_release must not be empty.")

    threshold = float(tau_network)
    active_mask = d_ref > threshold
    if not np.any(active_mask):
        raise ValueError("Reference network is empty.")
    q_ref_steady = float(np.sum(d_ref))
    if not np.isfinite(q_ref_steady) or q_ref_steady <= 0.0:
        raise ValueError("Reference steady drainage sum must be finite and > 0.")

    if d_tol is None:
        valid_area = cell_area_arr[np.isfinite(cell_area_arr) & (cell_area_arr > 0.0)]
        if valid_area.size == 0:
            raise ValueError("Cannot infer d_tol without positive cell areas.")
        d_tol_value = float(np.sqrt(np.nanmedian(valid_area)))
    else:
        d_tol_value = float(d_tol)
    if not np.isfinite(d_tol_value) or d_tol_value <= 0.0:
        raise ValueError("d_tol must be finite and > 0.")

    score_start = int(warmup_periods)
    if score_start < 0 or score_start >= q_ref.size:
        raise ValueError("warmup_periods must point inside transient_q_total_release.")
    score_stop = q_ref.size if scored_periods is None else score_start + int(scored_periods)
    if score_stop <= score_start or score_stop > q_ref.size:
        raise ValueError("scored_periods defines an invalid scoring window.")
    q_scored = q_ref[score_start:score_stop]
    finite_q = q_scored[np.isfinite(q_scored)]
    if finite_q.size == 0:
        raise ValueError("The scored Q_total_release window has no finite value.")
    qbar_ref = float(np.mean(finite_q))
    if qbar_ref <= 0.0:
        raise ValueError("Qbar_ref must be positive.")

    l_ref = equivalent_network_length(active_mask, cell_area_arr, d_tol=d_tol_value)

    if time_index is None:
        q_frame = pd.DataFrame(
            {
                "timestep": np.arange(q_ref.size, dtype=int),
                "q_total_release": q_ref,
            }
        )
    else:
        idx = pd.DatetimeIndex(time_index)
        if idx.size != q_ref.size:
            raise ValueError(f"time_index length must match q_ref ({idx.size} != {q_ref.size}).")
        q_frame = pd.DataFrame(
            {
                "datetime": idx.astype(str),
                "q_total_release": q_ref,
            }
        )

    normalization = {
        "tau_network": threshold,
        "Q_ref_steady": q_ref_steady,
        "L_ref": l_ref,
        "d_tol": d_tol_value,
        "eta_flux": float(eta_flux),
        "eta_dist": float(eta_dist),
        "eta_len": float(eta_len),
        "a_flux": float(a_flux),
        "a_dist": float(a_dist),
        "a_len": float(a_len),
        "Qbar_ref": qbar_ref,
        "alpha_Q": float(alpha_q),
        "w_reseau": float(w_network),
        "w_debit": float(w_discharge),
        "warmup_periods": score_start,
        "score_start_index": score_start,
        "score_stop_index": score_stop,
        "scored_periods": score_stop - score_start,
    }
    metadata_out = dict(metadata or {})
    metadata_out.setdefault("package_type", "network_transient_truth")
    metadata_out.setdefault("generated_at", datetime.now(UTC).isoformat())
    metadata_out.setdefault("n_cells", int(d_ref.size))
    metadata_out.setdefault("n_timesteps", int(q_ref.size))

    np.savez_compressed(out_dir / "steady_network_drain_by_cell.npz", outflow_drain=d_ref)
    np.savez_compressed(out_dir / "steady_network_active_mask.npz", active_mask=active_mask)
    np.savez_compressed(
        out_dir / "cell_geometry.npz", centroids=centroids_arr, cell_area=cell_area_arr
    )
    q_frame.to_csv(out_dir / "transient_q_total_release.csv", index=False)
    _write_json(out_dir / "normalization.json", normalization)
    _write_json(out_dir / "metadata.json", metadata_out)

    return TruthPackageSummary(
        output_dir=out_dir,
        q_ref_steady=q_ref_steady,
        qbar_ref=qbar_ref,
        l_ref=l_ref,
        n_cells=int(d_ref.size),
        n_timesteps=int(q_ref.size),
        n_ref_active=int(np.count_nonzero(active_mask)),
    )


def score_network_transient_candidate(
    truth_dir: str | Path,
    *,
    candidate_steady_drain_by_cell: object,
    candidate_q_total_release: object,
) -> CandidateScore:
    """Score one candidate against a written network/transient truth package."""

    truth_path = Path(truth_dir)
    normalization = _read_json(truth_path / "normalization.json")
    d_ref = np.load(truth_path / "steady_network_drain_by_cell.npz")["outflow_drain"]
    geometry = np.load(truth_path / "cell_geometry.npz")
    centroids = geometry["centroids"]
    cell_area = geometry["cell_area"]
    q_ref = pd.read_csv(truth_path / "transient_q_total_release.csv")["q_total_release"].to_numpy(
        dtype=float
    )

    network = network_cost(
        candidate_steady_drain_by_cell,
        d_ref,
        centroids,
        cell_area,
        d_tol=float(normalization["d_tol"]),
        q_ref_steady=float(normalization["Q_ref_steady"]),
        threshold=float(normalization["tau_network"]),
        eta_flux=float(normalization["eta_flux"]),
        eta_dist=float(normalization["eta_dist"]),
        eta_len=float(normalization["eta_len"]),
        weight_flux=float(normalization["a_flux"]),
        weight_dist=float(normalization["a_dist"]),
        weight_len=float(normalization["a_len"]),
    )

    start = int(normalization["score_start_index"])
    stop = int(normalization["score_stop_index"])
    q_sim = np.asarray(candidate_q_total_release, dtype=float).reshape(-1)
    if q_sim.size != q_ref.size:
        raise ValueError(
            f"candidate_q_total_release length must be {q_ref.size}, got {q_sim.size}."
        )
    discharge_cost, discharge_components = discharge_rmse_cost(
        q_sim[start:stop],
        q_ref[start:stop],
        alpha_q=float(normalization["alpha_Q"]),
        qbar_ref=float(normalization["Qbar_ref"]),
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
        "C_reseau_phys": float(network.total),
        "C_debit_phys": float(discharge_cost),
        "w_reseau": w_network,
        "w_debit": w_discharge,
    }
    components.update({f"network.{key}": float(value) for key, value in network.components.items()})
    components.update(
        {f"discharge.{key}": float(value) for key, value in discharge_components.items()}
    )
    return CandidateScore(total=total, components=components)


def score_network_transient_candidate_from_runs(
    truth_dir: str | Path,
    *,
    steady_run: Any,
    transient_run: Any,
) -> CandidateScore:
    """Score a candidate represented by two catalog ``Run`` objects."""

    steady_drain = np.asarray(steady_run.field("outflow_drain", timestep=-1), dtype=float).reshape(
        -1
    )
    q_total_release = _transient_q_total_release_from_run(transient_run)
    return score_network_transient_candidate(
        truth_dir,
        candidate_steady_drain_by_cell=steady_drain,
        candidate_q_total_release=q_total_release,
    )


def write_network_transient_truth_package_from_runs(
    output_dir: str | Path,
    *,
    steady_run: Any,
    transient_run: Any,
    metadata: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> TruthPackageSummary:
    """Build a truth package from two catalog ``Run`` objects."""

    steady_drain = np.asarray(steady_run.field("outflow_drain", timestep=-1), dtype=float).reshape(
        -1
    )
    q_total_release = _transient_q_total_release_from_run(transient_run)

    mesh = steady_run.mesh
    centroids, cell_area = mesh_cell_geometry(mesh.vertices, mesh.face_node_connectivity)
    if centroids.shape[0] != steady_drain.size:
        raise ValueError(
            "Steady outflow_drain size does not match mesh face count "
            f"({steady_drain.size} != {centroids.shape[0]})."
        )

    metadata_out = {
        "steady_sim_id": getattr(steady_run, "sim_id", None),
        "steady_name": getattr(steady_run, "name", None),
        "steady_solver": getattr(steady_run, "solver", None),
        "transient_sim_id": getattr(transient_run, "sim_id", None),
        "transient_name": getattr(transient_run, "name", None),
        "transient_solver": getattr(transient_run, "solver", None),
    }
    metadata_out.update(dict(metadata or {}))
    return write_network_transient_truth_package(
        output_dir,
        steady_drain_by_cell=steady_drain,
        transient_q_total_release=q_total_release,
        centroids=centroids,
        cell_area=cell_area,
        time_index=transient_run.time_index,
        metadata=metadata_out,
        **kwargs,
    )


def _transient_q_total_release_from_run(transient_run: Any) -> np.ndarray:
    """Read total release from a run, falling back to persisted catchment discharge."""

    try:
        transient_drain_stack = transient_run.fields("outflow_drain").data
        if hasattr(transient_drain_stack, "compute"):
            transient_drain_stack = transient_drain_stack.compute()
        return q_total_release_from_drain_by_cell(transient_drain_stack)
    except ModuleNotFoundError as exc:
        if exc.name != "dask":
            raise
    except Exception as exc:
        if "No module named 'dask'" not in str(exc):
            raise

    return np.asarray(transient_run.timeseries("discharge", "_catchment"), dtype=float).reshape(-1)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    "CandidateScore",
    "TruthPackageSummary",
    "discharge_rmse_cost",
    "mesh_cell_geometry",
    "q_total_release_from_drain_by_cell",
    "score_network_transient_candidate",
    "score_network_transient_candidate_from_runs",
    "write_network_transient_truth_package",
    "write_network_transient_truth_package_from_runs",
]
