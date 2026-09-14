"""Synthetic smoke test for the natural network/discharge calibration contract."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.observations.natural_observations import (  # noqa: E402
    score_natural_network_transient_candidate,
    write_natural_observation_package,
)
from hydromodpy.calibration.reporting import build_network_transient_html  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "outputs" / "synthetic_smoke"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    out = args.output_dir
    obs_dir = out / "natural_observation_package"
    candidate_dir = out / "candidates"
    web_dir = out / "web"
    out.mkdir(parents=True, exist_ok=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    centroids, area = _line_geometry()
    observed_network = np.array(
        [False, False, True, True, True, True, False, False, False, False],
        dtype=bool,
    )
    observed_distance = _distance_to_observed_line(observed_network.size)
    site_id = "synthetic_natural_smoke"
    observed_q = _observed_q()
    mesh_bundle = out / "mesh_bundle"
    _write_line_mesh_bundle(mesh_bundle, observed_network.size)

    write_natural_observation_package(
        obs_dir,
        observed_q_total_release=observed_q,
        observed_network_mask=observed_network,
        observed_network_distance_by_cell=observed_distance,
        centroids=centroids,
        cell_area=area,
        metadata={
            "site_id": site_id,
            "mesh_bundle": str(mesh_bundle.resolve()),
        },
        d_tol=1.0,
    )

    rows = []
    candidates = {
        "truth_identity": (observed_network.astype(float), observed_q, 0.65, 0.05),
        "shifted_network": (
            np.array([0, 0, 0, 0, 1, 1, 1, 1, 0, 0], dtype=float),
            observed_q,
            0.95,
            0.05,
        ),
        "high_discharge": (observed_network.astype(float), observed_q * 1.35, 0.65, 0.10),
        "combined_error": (
            np.array([0, 1, 1, 0, 0, 0, 0, 1, 1, 0], dtype=float),
            observed_q * 0.70,
            1.25,
            0.14,
        ),
    }
    for candidate_id, (network, q_total, mk, sy) in candidates.items():
        steady_path = candidate_dir / f"{candidate_id}_steady_drain.npz"
        q_path = candidate_dir / f"{candidate_id}_q_total_release.csv"
        np.savez_compressed(steady_path, outflow_drain=np.asarray(network, dtype=float))
        _write_q_csv(q_path, q_total)
        score = score_natural_network_transient_candidate(
            obs_dir,
            candidate_steady_drain_by_cell=network,
            candidate_q_total_release=q_total,
        )
        row: dict[str, Any] = {
            "candidate_id": candidate_id,
            "mK": mk,
            "Sy": sy,
            "status": "completed",
            "objective": score.total,
            "J": score.total,
            "error": "",
            "network_map_source": "steady",
            "steady_drain_npz": _rel(steady_path, out),
            "transient_q_csv": _rel(q_path, out),
        }
        row.update({key: float(value) for key, value in score.components.items()})
        row["C_reseau_phys"] = row["C_reseau_naturel"]
        row["C_debit_phys"] = row["C_debit_obs"]
        rows.append(row)

    rows.sort(key=lambda row: float(row["J"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    score_csv = out / f"{site_id}_candidate_scores.csv"
    _write_score_csv(score_csv, rows)
    (out / f"{site_id}_candidate_scores.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    build_network_transient_html(
        real_root=out,
        web_root=web_dir,
        source_transient_config=SCRIPT_DIR / "synthetic_natural_smoke.toml",
        path_base=out,
        page_title="Natural calibration smoke - reseau permanent + debit observe",
        truth_packages=[obs_dir],
        score_tables=[score_csv],
    )
    print(web_dir / "index.html")
    return 0


def _line_geometry(n_cells: int = 10) -> tuple[np.ndarray, np.ndarray]:
    centroids = np.column_stack(
        [np.arange(n_cells, dtype=float), np.zeros(n_cells, dtype=float)]
    )
    area = np.ones(n_cells, dtype=float)
    return centroids, area


def _observed_q(n_steps: int = 24) -> np.ndarray:
    t = np.arange(n_steps, dtype=float)
    return 1.0 + 0.25 * np.sin(2.0 * np.pi * t / 12.0) + 0.06 * np.cos(2.0 * np.pi * t / 6.0)


def _distance_to_observed_line(n_cells: int) -> np.ndarray:
    x = np.arange(n_cells, dtype=float)
    line_min = 2.5
    line_max = 4.5
    return np.where(x < line_min, line_min - x, np.where(x > line_max, x - line_max, 0.0))


def _write_line_mesh_bundle(bundle_dir: Path, n_cells: int) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    with (bundle_dir / "nodes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["node_id", "x", "y"])
        writer.writeheader()
        for idx in range(n_cells + 1):
            writer.writerow({"node_id": idx, "x": float(idx) - 0.5, "y": -0.5})
            writer.writerow({"node_id": idx + n_cells + 1, "x": float(idx) - 0.5, "y": 0.5})
    with (bundle_dir / "cells.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["cell_id", "n0", "n1", "n2", "n3", "area_m2", "z_top_mean"],
        )
        writer.writeheader()
        for cell_id in range(n_cells):
            writer.writerow(
                {
                    "cell_id": cell_id,
                    "n0": cell_id,
                    "n1": cell_id + 1,
                    "n2": cell_id + n_cells + 2,
                    "n3": cell_id + n_cells + 1,
                    "area_m2": 1.0,
                    "z_top_mean": 10.0 - 0.1 * cell_id,
                }
            )


def _write_q_csv(path: Path, values: np.ndarray) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestep", "q_total_release"])
        for idx, value in enumerate(np.asarray(values, dtype=float).reshape(-1)):
            writer.writerow([idx, f"{float(value):.16g}"])


def _write_score_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
