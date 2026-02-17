"""
Illustration of NSE, NSElog, and KGE on the coarse-sand reference example.

The script compares:
- observed series   = analytical recession (noise-free)
- simulated series  = noisy synthetic series
and visualizes both time-domain and scatter diagnostics.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from example_coarse_sand_profile import build_coarse_sand_profile
from objective_fucntion import ObjectiveFunction


def compute_metrics_for_coarse_sand():
    """
    Compute metrics comparing noisy series to analytical reference.

    Convention:
    - observed  = analytical (q_true)
    - simulated = noisy (q_noisy)

    Returns
    -------
    tuple
        `(params, t_days, q_true, q_noisy, metrics_dict)`.
    """
    # Reuse the profile builder to keep parameterization consistent across examples.
    params, _, t_days, q_true, q_noisy, _, _ = build_coarse_sand_profile()

    # ObjectiveFunction provides a unified interface and metric switch.
    objective = ObjectiveFunction(metric="nse")
    metrics = objective.evaluate_all(q_true, q_noisy)
    return params, t_days, q_true, q_noisy, metrics


def plot_metrics_illustration(params, t_days, q_true, q_noisy, metrics, output_png: Path):
    """
    Plot time-series and observed-vs-simulated scatter with metric summary.

    Figure layout:
    - left panel: temporal comparison on log-log axes,
    - right panel: scatter with 1:1 line for bias/spread inspection.
    """
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=140)
    ax_ts, ax_sc = axes

    # Left panel: time-series comparison
    # Mask non-positive noisy values to avoid invalid log-axis rendering.
    q_noisy_plot = np.where(q_noisy > 0.0, q_noisy, np.nan)
    ax_ts.plot(t_days, q_true, color="tab:blue", lw=2.0, label="Observed (analytical)")
    ax_ts.scatter(t_days, q_true, s=16, color="tab:blue", alpha=0.35)
    ax_ts.plot(t_days, q_noisy_plot, color="tab:orange", lw=1.4, ls="--", label="Simulated (noisy)")
    ax_ts.scatter(t_days, q_noisy_plot, s=20, color="tab:orange", alpha=0.85)
    ax_ts.set_xscale("log")
    ax_ts.set_yscale("log")
    ax_ts.set_xlabel("Time [days]")
    ax_ts.set_ylabel("Discharge [m^3/s]")
    ax_ts.set_title("Coarse-sand recession: observed vs simulated")
    ax_ts.grid(True, which="both", ls=":", alpha=0.45)
    ax_ts.legend(loc="best")

    # Right panel: scatter + 1:1 line
    # Dynamic bounds built from available data for a readable 1:1 reference.
    ax_sc.scatter(q_true, q_noisy, s=28, color="tab:purple", alpha=0.85, label="Point pairs")
    finite_min = np.nanmin(np.r_[q_true, q_noisy])
    finite_max = np.nanmax(np.r_[q_true, q_noisy])
    ax_sc.plot([finite_min, finite_max], [finite_min, finite_max], color="0.25", ls="--", lw=1.2, label="1:1 line")
    ax_sc.set_xscale("log")
    ax_sc.set_yscale("log")
    ax_sc.set_xlabel("Observed discharge [m^3/s]")
    ax_sc.set_ylabel("Simulated discharge [m^3/s]")
    ax_sc.set_title("Observed vs simulated")
    ax_sc.grid(True, which="both", ls=":", alpha=0.45)
    ax_sc.legend(loc="best")

    # Embed metrics directly in figure for quick interpretation.
    metric_text = (
        f"NSE    = {metrics['NSE']:.4f}\n"
        f"NSElog = {metrics['NSElog']:.4f}\n"
        f"KGE    = {metrics['KGE']:.4f}\n"
        f"r      = {metrics['r']:.4f}\n"
        f"alpha  = {metrics['alpha']:.4f}\n"
        f"beta   = {metrics['beta']:.4f}"
    )
    fig.text(
        0.50,
        0.05,
        metric_text,
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "0.7", "alpha": 0.95},
    )

    fig.suptitle(
        (
            "Hydrological performance metrics on coarse-sand example\n"
            f"(error_fraction={params['error_fraction']:.0%}, n_points={params['n_points']})"
        ),
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0.13, 1, 0.93])

    # Save artifact, then show figure for interactive inspection.
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, bbox_inches="tight")
    plt.show()


def main():
    """
    Run hydrological-metric illustration workflow.

    Workflow:
    1. build coarse-sand observed/simulated series,
    2. compute NSE, NSElog and KGE diagnostics,
    3. print values and generate the summary figure.
    """
    params, t_days, q_true, q_noisy, metrics = compute_metrics_for_coarse_sand()

    out_dir = Path(__file__).resolve().parent / "outputs"
    png_path = out_dir / "coarse_sand_metrics_illustration.png"

    print("Hydrological metrics (observed=analytical, simulated=noisy):")
    for key in ("NSE", "NSElog", "KGE", "r", "alpha", "beta"):
        print(f"  {key:7s}: {metrics[key]:.6f}")

    plot_metrics_illustration(params, t_days, q_true, q_noisy, metrics, png_path)
    print(f"Saved figure: {png_path}")


if __name__ == "__main__":
    main()
