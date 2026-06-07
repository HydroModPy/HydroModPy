"""Generate documentation assets for the Boussinesq lower-obstacle drying case."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt

from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_mixed import solve_transient_step

SECONDS_PER_DAY = 86_400.0
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "docs"
    / "readthedocs"
    / "source"
    / "_static"
    / "scientific"
    / "solvers"
    / "boussinesq"
)
DEFAULT_FIGURE_PATH = DEFAULT_OUTPUT_DIR / "lower_obstacle_drying_rewetting.png"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "lower_obstacle_drying_rewetting_summary.json"


@dataclass(frozen=True, slots=True)
class MiniMesh:
    """Minimal mesh contract needed by the PETSc mixed Boussinesq runtime."""

    cell_area_m2: np.ndarray
    z_top_m: np.ndarray
    z_bottom_m: np.ndarray
    hydraulic_conductivity_m_s: np.ndarray
    storage_coefficient: np.ndarray
    edge_ids: np.ndarray
    edge_cell_a: np.ndarray
    edge_cell_b: np.ndarray
    edge_length_m: np.ndarray
    edge_distance_m: np.ndarray
    edge_midpoint_distance_to_cell_a_m: np.ndarray
    edge_midpoint_distance_to_cell_b_m: np.ndarray

    @property
    def n_cells(self) -> int:
        return int(self.cell_area_m2.size)

    @property
    def n_edges(self) -> int:
        return int(self.edge_ids.size)


def build_sloping_hillslope_mesh(n_cells: int = 8) -> MiniMesh:
    """Return the steep one-dimensional hillslope used in the drying test."""
    edge_ids = np.arange(n_cells - 1, dtype=int)
    z_bottom = np.linspace(20.0, 0.0, n_cells, dtype=float)
    return MiniMesh(
        cell_area_m2=np.full(n_cells, 100.0, dtype=float),
        z_top_m=z_bottom + 1.5,
        z_bottom_m=z_bottom,
        hydraulic_conductivity_m_s=np.full(n_cells, 1.0e-3, dtype=float),
        storage_coefficient=np.full(n_cells, 0.2, dtype=float),
        edge_ids=edge_ids,
        edge_cell_a=edge_ids.copy(),
        edge_cell_b=edge_ids + 1,
        edge_length_m=np.full(n_cells - 1, 10.0, dtype=float),
        edge_distance_m=np.full(n_cells - 1, 10.0, dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.full(n_cells - 1, 5.0, dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.full(n_cells - 1, 5.0, dtype=float),
    )


def run_drying_rewetting_case() -> dict[str, np.ndarray]:
    """Run the drying/rewetting sequence and return arrays for plotting."""
    mesh = build_sloping_hillslope_mesh()
    options = NonlinearRuntimeOptions(
        regularization_radius=0.05,
        max_iterations=80,
        tol_residual_inf=1.0e-8,
    )
    prescribed_head = np.full(mesh.n_cells, np.nan, dtype=float)
    prescribed_head[-1] = mesh.z_bottom_m[-1]

    head = mesh.z_bottom_m + 1.0
    head_history = [head.copy()]
    dry_deficit_history = [np.zeros(mesh.n_cells, dtype=float)]
    surface_excess_history = [np.zeros(mesh.n_cells, dtype=float)]
    step_recharge = [0.0]
    elapsed_days = [0.0]
    labels = ["initial"]

    for label, dt_days, recharge_rate in (
        ("30 d dry", 30.0, 0.0),
        ("60 d dry", 30.0, 0.0),
        ("70 d rewet", 10.0, 2.0e-6),
    ):
        result = solve_transient_step(
            TransientStepInputs(
                mesh=mesh,
                head_prev_m=head,
                dt_seconds=dt_days * SECONDS_PER_DAY,
                head_initial_guess_m=head,
                recharge_rate_m_s=recharge_rate,
                well_flux_m3_s=np.zeros(mesh.n_cells, dtype=float),
                prescribed_head_m_by_cell=prescribed_head,
                options=options,
            )
        )
        if not result.converged:
            raise RuntimeError(f"PETSc solve failed for {label}: {result.termination_reason}")
        head = np.asarray(result.head_m, dtype=float)
        head_history.append(head.copy())
        dry_deficit_history.append(np.asarray(result.assembly.dry_deficit_rate_m_s, dtype=float))
        surface_excess_history.append(
            np.asarray(result.assembly.saturation_excess_rate_m_s, dtype=float)
        )
        step_recharge.append(float(recharge_rate))
        elapsed_days.append(float(elapsed_days[-1] + dt_days))
        labels.append(label)

    return {
        "cell_index": np.arange(mesh.n_cells, dtype=int),
        "z_top_m": mesh.z_top_m,
        "z_bottom_m": mesh.z_bottom_m,
        "cell_area_m2": mesh.cell_area_m2,
        "head_history_m": np.vstack(head_history),
        "dry_deficit_history_m_s": np.vstack(dry_deficit_history),
        "surface_excess_history_m_s": np.vstack(surface_excess_history),
        "recharge_history_m_s": np.asarray(step_recharge, dtype=float),
        "elapsed_days": np.asarray(elapsed_days, dtype=float),
        "labels": np.asarray(labels, dtype=object),
    }


def write_summary(path: Path, data: dict[str, np.ndarray]) -> None:
    """Write one compact JSON summary beside the generated figure."""
    head = np.asarray(data["head_history_m"], dtype=float)
    bottom = np.asarray(data["z_bottom_m"], dtype=float).reshape(1, -1)
    dry = np.maximum(np.asarray(data["dry_deficit_history_m_s"], dtype=float), 0.0)
    area = np.asarray(data["cell_area_m2"], dtype=float).reshape(1, -1)
    payload = {
        "case": "boussinesq_lower_obstacle_drying_rewetting",
        "elapsed_days": [float(value) for value in data["elapsed_days"].tolist()],
        "labels": [str(value) for value in data["labels"].tolist()],
        "min_head_above_bottom_m": [
            float(value) for value in np.min(head - bottom, axis=1).tolist()
        ],
        "dry_deficit_active_cell_count": [
            int(value) for value in np.sum(dry > 1.0e-12, axis=1).tolist()
        ],
        "dry_deficit_total_m3_day": [
            float(value) for value in (np.sum(dry * area, axis=1) * SECONDS_PER_DAY).tolist()
        ],
        "max_recharge_mm_day": float(
            np.max(np.asarray(data["recharge_history_m_s"], dtype=float))
            * SECONDS_PER_DAY
            * 1_000.0
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_figure(path: Path, data: dict[str, np.ndarray]) -> None:
    """Write the drying/rewetting diagnostic figure."""
    x = np.asarray(data["cell_index"], dtype=float)
    top = np.asarray(data["z_top_m"], dtype=float)
    bottom = np.asarray(data["z_bottom_m"], dtype=float)
    head = np.asarray(data["head_history_m"], dtype=float)
    dry = np.maximum(np.asarray(data["dry_deficit_history_m_s"], dtype=float), 0.0)
    surface = np.maximum(np.asarray(data["surface_excess_history_m_s"], dtype=float), 0.0)
    recharge = np.asarray(data["recharge_history_m_s"], dtype=float)
    elapsed_days = np.asarray(data["elapsed_days"], dtype=float)
    labels = [str(value) for value in data["labels"].tolist()]
    area = np.asarray(data["cell_area_m2"], dtype=float).reshape(1, -1)

    saturated_thickness = np.clip(head - bottom.reshape(1, -1), 0.0, top - bottom)
    dry_cell_count = np.sum(dry > 1.0e-12, axis=1)
    dry_total_m3_day = np.sum(dry * area, axis=1) * SECONDS_PER_DAY
    surface_total_m3_day = np.sum(surface * area, axis=1) * SECONDS_PER_DAY
    recharge_mm_day = recharge * SECONDS_PER_DAY * 1_000.0

    figure, axes = plt.subplots(3, 1, figsize=(9.8, 10.2), constrained_layout=True)
    profile_ax, thickness_ax, flux_ax = axes
    palette = ["#111827", "#d97706", "#dc2626", "#2563eb"]

    profile_ax.fill_between(
        x,
        bottom,
        top,
        color="#dbeafe",
        alpha=0.45,
        step="mid",
        label="Saturable thickness",
    )
    profile_ax.plot(x, top, color="#15803d", linewidth=2.0, label="Surface")
    profile_ax.plot(x, bottom, color="#7c2d12", linewidth=2.0, label="Substratum")
    for idx, label in enumerate(labels):
        profile_ax.plot(
            x,
            head[idx],
            marker="o",
            linewidth=1.7,
            markersize=4.5,
            color=palette[idx],
            label=f"Head: {label}",
        )
    active_dry = dry[-2] > 1.0e-12
    if np.any(active_dry):
        profile_ax.scatter(
            x[active_dry],
            bottom[active_dry],
            s=70,
            facecolor="#fef2f2",
            edgecolor="#dc2626",
            linewidth=1.4,
            zorder=5,
            label="Dry constraint active at 60 d",
        )
    profile_ax.set_title("Steep hillslope: lower obstacle activation", loc="left")
    profile_ax.set_ylabel("Elevation [m]")
    profile_ax.set_xlabel("Cell index, upstream to downstream")
    profile_ax.grid(True, alpha=0.2)
    profile_ax.legend(loc="upper right", fontsize=8, ncol=2, frameon=False)

    thickness_ax.plot(
        elapsed_days,
        np.min(saturated_thickness, axis=1),
        marker="o",
        color="#7c2d12",
        linewidth=1.8,
        label="Minimum H",
    )
    thickness_ax.plot(
        elapsed_days,
        np.mean(saturated_thickness, axis=1),
        marker="o",
        color="#2563eb",
        linewidth=1.8,
        label="Mean H",
    )
    thickness_ax.plot(
        elapsed_days,
        np.max(saturated_thickness, axis=1),
        marker="o",
        color="#15803d",
        linewidth=1.8,
        label="Maximum H",
    )
    dry_count_ax = thickness_ax.twinx()
    dry_count_ax.step(
        elapsed_days,
        dry_cell_count,
        where="post",
        color="#dc2626",
        linewidth=1.6,
        linestyle="--",
        label="q_dry active cells",
    )
    thickness_ax.set_title(
        "Drying lowers stored saturated thickness, rewetting restores it", loc="left"
    )
    thickness_ax.set_ylabel("Saturated thickness H [m]")
    thickness_ax.set_xlabel("Elapsed time [d]")
    dry_count_ax.set_ylabel("Dry cells")
    thickness_ax.grid(True, alpha=0.2)
    handles_a, labels_a = thickness_ax.get_legend_handles_labels()
    handles_b, labels_b = dry_count_ax.get_legend_handles_labels()
    thickness_ax.legend(
        handles_a + handles_b, labels_a + labels_b, loc="upper right", frameon=False
    )

    flux_ax.bar(
        elapsed_days,
        recharge_mm_day,
        width=4.0,
        color="#bfdbfe",
        edgecolor="#2563eb",
        label="Recharge [mm/d]",
    )
    flux2_ax = flux_ax.twinx()
    flux2_ax.step(
        elapsed_days,
        dry_total_m3_day,
        where="post",
        color="#dc2626",
        linewidth=1.8,
        label="Dry deficit [m3/d]",
    )
    flux2_ax.step(
        elapsed_days,
        surface_total_m3_day,
        where="post",
        color="#9333ea",
        linewidth=1.6,
        linestyle=":",
        label="Surface excess [m3/d]",
    )
    flux_ax.set_title("q_dry is active only during drying demand, not during rewetting", loc="left")
    flux_ax.set_ylabel("Recharge [mm/d]")
    flux2_ax.set_ylabel("Integrated constraint flux [m3/d]")
    flux_ax.set_xlabel("Elapsed time [d]")
    flux_ax.grid(True, alpha=0.2)
    handles_a, labels_a = flux_ax.get_legend_handles_labels()
    handles_b, labels_b = flux2_ax.get_legend_handles_labels()
    flux_ax.legend(handles_a + handles_b, labels_a + labels_b, loc="upper right", frameon=False)

    figure.suptitle("Boussinesq lower obstacle: drying and rewetting diagnostic", fontsize=14)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    data = run_drying_rewetting_case()
    write_figure(DEFAULT_FIGURE_PATH, data)
    write_summary(DEFAULT_SUMMARY_PATH, data)
    print(f"Wrote {DEFAULT_FIGURE_PATH}")
    print(f"Wrote {DEFAULT_SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
