"""
Example script: coarse-sand Brutsaert recession profile generation and plotting.

The script:
1. defines a physically plausible coarse-sand parameter set,
2. generates analytical and noisy discharge series,
3. exports both figure and CSV point cloud.
"""

from pathlib import Path
import sys

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from reference_cases.recession_brutsaert.baseflow import generate_noisy_baseflow_profile


# Coarse sand ranges from README:
# K  in [1e-5, 1e-3] m/s
# Sy in [0.20, 0.35] -
K_COARSE_SAND_RANGE = (1e-5, 1e-3)
SY_COARSE_SAND_RANGE = (0.20, 0.35)


def build_coarse_sand_profile():
    """
    Build a synthetic coarse-sand profile used as reference/example data.

    Returns
    -------
    tuple
        `(params, t_seconds, t_days, q_true, q_noisy, tc_seconds, sigma)`.
    """
    # Parameterization intentionally kept inside coarse-sand ranges from README.
    params = {
        "Q0": 0.35,         # m^3/s
        "K": 2.0e-4,        # m/s  (inside coarse sand range)
        "Sy": 0.28,         # -    (inside coarse sand range)
        "solution": "boussinesq",
        "A": 1.2e6,         # m^2
        "ag": 0.7,          # -
        "p": 0.346,         # -
        "n_points": 50,
        "log_spacing": True,
        "t_min_days": 0.1,
        "error_fraction": 0.10,
        "random_seed": 12345,
    }

    # Defensive checks to avoid accidentally drifting outside intended ranges.
    k_min, k_max = K_COARSE_SAND_RANGE
    sy_min, sy_max = SY_COARSE_SAND_RANGE
    if not (k_min <= params["K"] <= k_max):
        raise ValueError("K must remain in coarse sand range")
    if not (sy_min <= params["Sy"] <= sy_max):
        raise ValueError("Sy must remain in coarse sand range")

    # Generate deterministic and noisy chronicle in one call.
    t_s, t_days, q_true, q_noisy, tc_s, sigma = generate_noisy_baseflow_profile(**params)
    return params, t_s, t_days, q_true, q_noisy, tc_s, sigma


def plot_profile(params, t_days, q_true, q_noisy, tc_s, output_png: Path, show_plot=False):
    """
    Plot analytical/noisy profiles with clear labels and save as PNG.

    Parameters
    ----------
    show_plot : bool
        If True, display the figure interactively after saving.
    """
    tc_days = tc_s / 86400.0

    fig, ax = plt.subplots(figsize=(10, 5), dpi=140)

    # Reference analytical profile (line + markers).
    ax.plot(
        t_days,
        q_true,
        color="tab:blue",
        lw=2.2,
        label="Analytical profile (no error)",
    )
    ax.scatter(
        t_days,
        q_true,
        s=18,
        color="tab:blue",
        alpha=0.35,
        label=f"Analytical points (n={len(t_days)})",
    )

    # Log-scale plotting requires strictly positive y values.
    # Non-positive noisy values are masked to NaN for robust rendering.
    q_noisy_plot = np.where(q_noisy > 0.0, q_noisy, np.nan)
    ax.plot(
        t_days,
        q_noisy_plot,
        color="tab:orange",
        lw=1.2,
        ls="--",
        alpha=0.9,
        label=f"Noisy profile (error_fraction={params['error_fraction']:.0%})",
    )
    ax.scatter(
        t_days,
        q_noisy_plot,
        s=22,
        color="tab:orange",
        marker="o",
        alpha=0.85,
        label="Noisy points",
    )
    ax.axvline(
        tc_days,
        color="tab:red",
        ls="--",
        lw=1.6,
        label=f"Characteristic time tc = {tc_days:.1f} d",
    )

    # Log-log visualization is standard for recession diagnostics.
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Time since recession start [days]")
    ax.set_ylabel("Discharge Q(t) [m^3/s]")
    ax.set_title("Brutsaert recession profile with coarse-sand parameters")
    ax.grid(True, which="both", ls=":", alpha=0.45)

    # Compact metadata block for figure self-documentation.
    text = (
        f"Q0={params['Q0']:.2f} m^3/s, "
        f"K={params['K']:.1e} m/s, Sy={params['Sy']:.2f}\n"
        f"A={params['A']:.2e} m^2, ag={params['ag']:.2f}, "
        f"f={params['error_fraction']:.2f}"
    )
    ax.text(
        0.02,
        0.03,
        text,
        transform=ax.transAxes,
        fontsize=9,
        va="bottom",
        ha="left",
        bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "0.7", "alpha": 0.9},
    )

    ax.legend(loc="best", title="Legend")
    fig.tight_layout()

    # Ensure output folder exists before writing artifacts.
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, bbox_inches="tight")
    if show_plot:
        plt.show()
    else:
        plt.close(fig)


def save_points_csv(t_days, q, output_csv: Path):
    """
    Save generated points as CSV for quick inspection or downstream scripts.

    The CSV contains:
    - time [days]
    - true discharge [m^3/s]
    - noisy discharge [m^3/s]
    - sigma used for noise [m^3/s]
    """
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    q_true, q_noisy, sigma = q
    data = np.column_stack([t_days, q_true, q_noisy, sigma])
    header = "time_days,discharge_true_m3_per_s,discharge_noisy_m3_per_s,sigma_m3_per_s"
    np.savetxt(output_csv, data, delimiter=",", header=header, comments="")


def main():
    """
    Run full coarse-sand profile generation workflow.

    Workflow:
    1. build deterministic and noisy series,
    2. produce and optionally display figure,
    3. export points to CSV for later reuse.
    """
    params, _, t_days, q_true, q_noisy, tc_s, sigma = build_coarse_sand_profile()

    out_dir = Path(__file__).resolve().parent / "outputs"
    png_path = out_dir / "coarse_sand_recession_profile.png"
    csv_path = out_dir / "coarse_sand_recession_points.csv"

    plot_profile(params, t_days, q_true, q_noisy, tc_s, png_path, show_plot=True)
    save_points_csv(t_days, (q_true, q_noisy, sigma), csv_path)

    print(f"Saved figure: {png_path}")
    print(f"Saved points: {csv_path}")


if __name__ == "__main__":
    main()
