"""Probe dry-equilibrium behavior with optional Boussinesq thickness floors."""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def _ensure_repo_on_path() -> None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hydromodpy").is_dir():
            sys.path.insert(0, str(parent))
            return


_ensure_repo_on_path()

from hydromodpy.solver.boussinesq.runtimes.dry_equilibrium import (
    assemble_effective_steady_balance,
    detect_dry_equilibrium,
)

DEFAULT_OUTPUT_DIR = "docs/_dev_notes/diagnostics/boussinesq_dry_equilibrium_probe"


@dataclass
class _LineMesh:
    cell_area_m2: np.ndarray
    z_top_m: np.ndarray
    z_bottom_m: np.ndarray
    hydraulic_conductivity_m_s: np.ndarray
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--b-min",
        action="append",
        type=float,
        dest="b_mins",
        help="Minimum effective saturated thickness to test. Can be repeated.",
    )
    args = parser.parse_args(argv)
    b_mins = args.b_mins or [0.0, 0.01, 0.05, 0.10, 0.50]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = list(_run_probe(b_mins))
    csv_path = output_dir / "dry_equilibrium_probe.csv"
    md_path = output_dir / "dry_equilibrium_probe.md"
    _write_csv(csv_path, rows)
    _write_markdown(md_path, rows)
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    return 0


def _run_probe(b_mins: Iterable[float]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    scenarios = {
        "flat_2_cells": [0.0, 0.0],
        "mild_slope_2_cells": [0.10, 0.0],
        "steep_slope_2_cells": [1.0, 0.0],
        "mild_slope_4_cells": [0.30, 0.20, 0.10, 0.0],
    }
    for scenario, z_bottom in scenarios.items():
        mesh = _mesh(z_bottom)
        for b_min in b_mins:
            result = detect_dry_equilibrium(
                mesh,
                recharge_rate_m_s=0.0,
                minimum_saturated_thickness_m=float(b_min),
            )
            balance = assemble_effective_steady_balance(
                mesh,
                mesh.z_bottom_m,
                recharge_rate_m_s=0.0,
                minimum_saturated_thickness_m=float(b_min),
            )
            max_flux = _finite_max(np.abs(balance.internal_edge_flux_m3_s)) or 0.0
            total_abs_flux = _finite_sum(np.abs(balance.internal_edge_flux_m3_s)) or 0.0
            rows.append(
                {
                    "scenario": scenario,
                    "b_min": float(b_min),
                    "max_flux": max_flux,
                    "total_abs_flux": total_abs_flux,
                    "residual_inf_at_h_bottom": _finite_max(np.abs(balance.residual_m3_s)) or 0.0,
                    "dry_equilibrium_detected": bool(result.detected),
                    "physical_dry_count": result.diagnostics["cells_physically_dry_count"],
                    "effective_floor_count": result.diagnostics["cells_at_effective_floor_count"],
                    "vi_violations_count": int(result.vi_violations_count),
                    "rejected_reason": result.rejected_reason or "",
                    "comment": _comment(result.detected, max_flux, float(b_min)),
                }
            )
    return rows


def _mesh(z_bottom: list[float], *, k_m_s: float = 1.0e-5) -> _LineMesh:
    n_cells = len(z_bottom)
    n_edges = max(n_cells - 1, 0)
    return _LineMesh(
        cell_area_m2=np.ones(n_cells, dtype=float),
        z_bottom_m=np.asarray(z_bottom, dtype=float),
        z_top_m=np.asarray(z_bottom, dtype=float) + 10.0,
        hydraulic_conductivity_m_s=np.full(n_cells, float(k_m_s), dtype=float),
        edge_ids=np.arange(n_edges, dtype=int),
        edge_cell_a=np.arange(n_edges, dtype=int),
        edge_cell_b=np.arange(1, n_cells, dtype=int),
        edge_length_m=np.ones(n_edges, dtype=float),
        edge_distance_m=np.ones(n_edges, dtype=float),
        edge_midpoint_distance_to_cell_a_m=0.5 * np.ones(n_edges, dtype=float),
        edge_midpoint_distance_to_cell_b_m=0.5 * np.ones(n_edges, dtype=float),
    )


def _comment(detected: bool, max_flux: float, b_min: float) -> str:
    if detected:
        return "accepted dry VI equilibrium"
    if b_min > 0.0 and max_flux > 0.0:
        return "effective floor creates a downslope film flux"
    return "dry VI equilibrium rejected"


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "scenario",
        "b_min",
        "max_flux",
        "total_abs_flux",
        "residual_inf_at_h_bottom",
        "dry_equilibrium_detected",
        "physical_dry_count",
        "effective_floor_count",
        "vi_violations_count",
        "rejected_reason",
        "comment",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [
        "# Boussinesq dry equilibrium probe",
        "",
        "| scenario | b_min | dry accepted | max flux m3/s | residual inf | comment |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {scenario} | {b_min:.3g} | {dry_equilibrium_detected} | "
            "{max_flux:.3e} | {residual_inf_at_h_bottom:.3e} | {comment} |".format(**row)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _finite_values(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    return array[np.isfinite(array)]


def _finite_max(values: np.ndarray) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.max(finite))


def _finite_sum(values: np.ndarray) -> float | None:
    finite = _finite_values(values)
    return None if finite.size == 0 else float(np.sum(finite))


if __name__ == "__main__":
    raise SystemExit(main())
