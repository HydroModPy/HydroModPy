"""Run a synthetic B0 truth/candidate scoring smoke test.

The script does not launch MODFLOW 6. It exercises the B0 metric contract with
deterministic arrays so the truth package, candidate scoring and ranking logic
can be checked without depending on heavy catalogs.
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.network_transient_truth import (
    score_network_transient_candidate,
    write_network_transient_truth_package,
)


DEFAULT_MK_VALUES = (0.5, 0.75, 1.0, 1.25, 1.5)
DEFAULT_SY_VALUES = (0.03, 0.05, 0.08, 0.12)
TRUE_MK = 1.0
TRUE_SY = 0.05


def run_synthetic_smoke(
    output_dir: str | Path,
    *,
    mK_values: list[float] | tuple[float, ...] = DEFAULT_MK_VALUES,
    Sy_values: list[float] | tuple[float, ...] = DEFAULT_SY_VALUES,
) -> pd.DataFrame:
    """Generate a synthetic truth package and rank a small candidate grid."""

    out_dir = Path(output_dir)
    truth_dir = out_dir / "truth"
    out_dir.mkdir(parents=True, exist_ok=True)

    centroids, cell_area = _toy_cell_geometry(nx=5, ny=5, dx=1.0)
    recharge = _monthly_recharge_series(n_months=48)
    d_ref = _toy_steady_network(TRUE_MK)
    q_ref = _toy_transient_q_total_release(recharge, mK=TRUE_MK, Sy=TRUE_SY)
    time_index = pd.date_range("2020-01-01", periods=q_ref.size, freq="MS")

    summary = write_network_transient_truth_package(
        truth_dir,
        steady_drain_by_cell=d_ref,
        transient_q_total_release=q_ref,
        centroids=centroids,
        cell_area=cell_area,
        time_index=time_index,
        metadata={
            "source": "synthetic_smoke",
            "site_id": "toy_5x5",
            "mK_true": TRUE_MK,
            "Sy_true": TRUE_SY,
        },
        tau_network=0.0,
        d_tol=1.0,
        alpha_q=0.10,
        warmup_periods=12,
        scored_periods=36,
    )

    rows: list[dict[str, Any]] = []
    for mK in mK_values:
        for Sy in Sy_values:
            d_sim = _toy_steady_network(float(mK))
            q_sim = _toy_transient_q_total_release(recharge, mK=float(mK), Sy=float(Sy))
            score = score_network_transient_candidate(
                truth_dir,
                candidate_steady_drain_by_cell=d_sim,
                candidate_q_total_release=q_sim,
            )
            row = {
                "candidate_id": f"mK_{float(mK):.3g}__Sy_{float(Sy):.3g}",
                "mK": float(mK),
                "Sy": float(Sy),
                "status": "completed",
                "objective": float(score.total),
            }
            row.update({key: float(value) for key, value in score.components.items()})
            rows.append(row)

    frame = pd.DataFrame(rows).sort_values("objective", ascending=True).reset_index(drop=True)
    frame.insert(0, "rank", range(1, len(frame) + 1))

    scores_csv = out_dir / "candidate_scores.csv"
    scores_json = out_dir / "candidate_scores.json"
    summary_json = out_dir / "summary.json"
    frame.to_csv(scores_csv, index=False)
    scores_json.write_text(
        json.dumps(frame.to_dict(orient="records"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_json.write_text(
        json.dumps(
            {
                "truth_dir": str(truth_dir),
                "scores_csv": str(scores_csv),
                "n_candidates": int(len(frame)),
                "truth": {
                    "q_ref_steady": summary.q_ref_steady,
                    "qbar_ref": summary.qbar_ref,
                    "l_ref": summary.l_ref,
                    "n_cells": summary.n_cells,
                    "n_timesteps": summary.n_timesteps,
                    "n_ref_active": summary.n_ref_active,
                    "mK_true": TRUE_MK,
                    "Sy_true": TRUE_SY,
                },
                "best": frame.iloc[0].to_dict(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return frame


def _toy_cell_geometry(*, nx: int, ny: int, dx: float) -> tuple[np.ndarray, np.ndarray]:
    x = np.arange(nx, dtype=float) * dx
    y = np.arange(ny, dtype=float) * dx
    xx, yy = np.meshgrid(x, y)
    centroids = np.column_stack([xx.reshape(-1), yy.reshape(-1)])
    cell_area = np.full(nx * ny, dx * dx, dtype="float64")
    return centroids, cell_area


def _toy_steady_network(mK: float) -> np.ndarray:
    """Return a 5x5 active network with one trunk and one tributary."""

    values = np.zeros((5, 5), dtype="float64")
    values[:, 2] = np.asarray([0.7, 1.0, 1.3, 1.0, 0.7], dtype="float64")
    values[2, 1] = 0.35
    values[2, 3] = 0.35
    return (float(mK) * values).reshape(-1)


def _monthly_recharge_series(*, n_months: int) -> np.ndarray:
    t = np.arange(n_months, dtype=float)
    seasonal = 1.0 + 0.35 * np.sin(2.0 * np.pi * (t - 2.0) / 12.0)
    pulses = np.zeros(n_months, dtype="float64")
    pulses[[5, 16, 29, 40]] = np.asarray([0.6, 0.4, 0.7, 0.5], dtype="float64")
    return 1.0e-3 * (seasonal + pulses)


def _toy_transient_q_total_release(recharge: np.ndarray, *, mK: float, Sy: float) -> np.ndarray:
    """Simple reservoir response used only for the synthetic smoke test."""

    forcing = np.asarray(recharge, dtype=float) * float(mK)
    sy_ratio = max(float(Sy), 1.0e-6) / TRUE_SY
    k_ratio = max(float(mK), 1.0e-6) / TRUE_MK
    response_time = max(1.0, 2.5 * sy_ratio / np.sqrt(k_ratio))
    alpha = 1.0 - np.exp(-1.0 / response_time)

    q = np.zeros_like(forcing)
    q[0] = forcing[0]
    for index in range(1, forcing.size):
        q[index] = q[index - 1] + alpha * (forcing[index] - q[index - 1])
    recharge_mean = float(np.mean(np.asarray(recharge, dtype=float)))
    return q * (np.sum(_toy_steady_network(TRUE_MK)) / recharge_mean)


def _parse_float_list(text: str) -> list[float]:
    values = [float(item.strip()) for item in text.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("Expected at least one comma-separated float.")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "outputs" / "synthetic_smoke",
        help="Directory where the synthetic truth package and score table are written.",
    )
    parser.add_argument(
        "--mK-values",
        type=_parse_float_list,
        default=list(DEFAULT_MK_VALUES),
        help="Comma-separated hydraulic-conductivity multipliers.",
    )
    parser.add_argument(
        "--Sy-values",
        type=_parse_float_list,
        default=list(DEFAULT_SY_VALUES),
        help="Comma-separated specific-yield values.",
    )
    args = parser.parse_args(argv)

    frame = run_synthetic_smoke(
        args.output_dir,
        mK_values=args.mK_values,
        Sy_values=args.Sy_values,
    )
    best = frame.iloc[0]
    print(f"Wrote synthetic B0 smoke outputs: {args.output_dir}")
    print(f"  candidates={len(frame)}")
    print(
        "  best="
        f"{best['candidate_id']} "
        f"J={float(best['objective']):.12g} "
        f"mK={float(best['mK']):.6g} "
        f"Sy={float(best['Sy']):.6g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
