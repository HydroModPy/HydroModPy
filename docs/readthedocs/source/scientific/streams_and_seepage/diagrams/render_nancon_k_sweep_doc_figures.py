# ruff: noqa: I001
"""Render committed Nancon K-sweep documentation figures from workflow outputs.

The script intentionally reads the same CSV exports that users inspect after a
comparison run. It does not hard-code metric values in the images.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[6]
DOC_STATIC_ROOT = (
    REPO_ROOT / "docs" / "readthedocs" / "source" / "_static" / "workflows"
    / "simulated_active_network"
)
COMPARISON_ROOT = REPO_ROOT / "examples" / "projects" / "09_comparison_workflow" / "outputs"


@dataclass(frozen=True)
class SweepSpec:
    name: str
    source_root: Path
    docs_dir: Path
    variants: tuple[str, ...]
    title: str


SWEEPS: tuple[SweepSpec, ...] = (
    SweepSpec(
        name="wide",
        source_root=COMPARISON_ROOT / "nancon_transient_seasonal_hydrography_wide_k_sweep_mf6",
        docs_dir=DOC_STATIC_ROOT / "nancon_wide_k_sweep",
        variants=("k_5e5", "k_1e4", "k_2e4", "k_5e4"),
        title="Nancon MODFLOW 6 wide K-sweep",
    ),
    SweepSpec(
        name="extreme",
        source_root=COMPARISON_ROOT / "nancon_transient_seasonal_hydrography_extreme_k_sweep_mf6",
        docs_dir=DOC_STATIC_ROOT / "nancon_extreme_k_sweep",
        variants=("k_2e6", "k_2e5", "k_2e4", "k_2e2"),
        title="Nancon MODFLOW 6 extreme K-sweep",
    ),
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required metrics export: {path}")
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _by_variant(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {str(row.get("variant_id", "")): row for row in rows}


def _float(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _int(row: dict[str, str], key: str) -> int | None:
    value = _float(row, key)
    if not math.isfinite(value):
        return None
    return int(round(value))


def _format_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,}".replace(",", " ")


def _format_ratio(value: float) -> str:
    if not math.isfinite(value):
        return "n/a"
    return f"{value:.3f}"


def _format_distance(value: float) -> str:
    if not math.isfinite(value):
        return "n/a"
    return f"{value:.0f} m"


def _format_k(value: float) -> str:
    if not math.isfinite(value):
        return "n/a"
    mantissa, exponent = f"{value:.3e}".split("e")
    mantissa = mantissa.rstrip("0").rstrip(".")
    return f"{mantissa}e{int(exponent)}"


def _parse_k(variant_id: str, label: str) -> float:
    match = re.search(r"K\s*=\s*([0-9.]+e[-+]?\d+)", label)
    if match:
        return float(match.group(1))
    match = re.fullmatch(r"k_([0-9]+(?:p[0-9]+)?)e([0-9]+)", variant_id)
    if not match:
        return float("nan")
    coefficient = float(match.group(1).replace("p", "."))
    exponent = int(match.group(2))
    return coefficient * 10.0 ** (-exponent)


def _merged_metrics(spec: SweepSpec) -> list[dict[str, object]]:
    occupancy = _by_variant(_read_csv(spec.source_root / "simulated_active_network_metrics.csv"))
    overlap = _by_variant(_read_csv(spec.source_root / "simulated_active_network_overlap_metrics.csv"))
    distance = _by_variant(_read_csv(spec.source_root / "simulated_active_network_distance_metrics.csv"))
    rows: list[dict[str, object]] = []
    for variant_id in spec.variants:
        if variant_id not in overlap:
            continue
        row: dict[str, object] = {}
        row.update(occupancy.get(variant_id, {}))
        row.update(overlap.get(variant_id, {}))
        row.update(distance.get(variant_id, {}))
        label = str(row.get("variant_label", variant_id))
        row["variant_id"] = variant_id
        row["K_m_s"] = _parse_k(variant_id, label)
        rows.append(row)
    rows.sort(key=lambda item: float(item["K_m_s"]))
    return rows


def _distance_log10_balance(row: dict[str, object]) -> float:
    as_str = {key: str(value) for key, value in row.items()}
    value = _float(as_str, "planar_distance_log10_balance")
    if math.isfinite(value):
        return value
    sim_to_ref = _float(as_str, "sim_to_network_distance_mean_m")
    ref_to_sim = _float(as_str, "network_to_sim_distance_mean_m")
    if sim_to_ref <= 0.0 or ref_to_sim <= 0.0:
        return float("nan")
    return float(math.log10(sim_to_ref / ref_to_sim))


def _format_log_balance(value: float) -> str:
    if not math.isfinite(value):
        return "n/a"
    return f"{value:+.2f}"


def _metric_items(row: dict[str, object]) -> list[tuple[str, str]]:
    as_str = {key: str(value) for key, value in row.items()}
    return [
        (r"$K$", f"{_format_k(float(row['K_m_s']))} m/s"),
        (r"$N_a$", _format_int(_int(as_str, "active_cell_count"))),
        (r"$N_{ref}$", _format_int(_int(as_str, "network_cell_count"))),
        (r"$N_{ov}$", _format_int(_int(as_str, "overlap_cell_count"))),
        (r"$N_{miss}$", _format_int(_int(as_str, "missing_network_cell_count"))),
        (r"$N_{extra}$", _format_int(_int(as_str, "extra_active_cell_count"))),
        (r"$C_{ref}$", _format_ratio(_float(as_str, "network_coverage_ratio"))),
        (r"$P_a$", _format_ratio(_float(as_str, "active_precision_ratio"))),
        (r"$F_1$", _format_ratio(_float(as_str, "cell_f1_ratio"))),
        (
            r"$D^{plan}_{s\to ref}$",
            _format_distance(_float(as_str, "sim_to_network_distance_mean_m")),
        ),
        (
            r"$D^{plan}_{ref\to s}$",
            _format_distance(_float(as_str, "network_to_sim_distance_mean_m")),
        ),
        (r"$\bar{D}^{plan}$", _format_distance(_float(as_str, "bidirectional_distance_mean_m"))),
        (r"$\log_{10} R_D^{plan}$", _format_log_balance(_distance_log10_balance(row))),
    ]


def _render_metric_band(ax: plt.Axes, row: dict[str, object]) -> None:
    ax.set_axis_off()
    ax.set_facecolor("#f6f7f8")
    items = _metric_items(row)
    columns = 3
    left = 0.035
    width = 0.93 / columns
    y_positions = (0.88, 0.71, 0.54, 0.37, 0.20)
    for idx, (label, value) in enumerate(items):
        col = idx % columns
        row_index = idx // columns
        x = left + col * width + width / 2.0
        y = y_positions[row_index]
        ax.text(
            x,
            y,
            f"{label}\n{value}",
            ha="center",
            va="center",
            fontsize=13.2,
            color="#1d2733",
            linespacing=1.28,
            transform=ax.transAxes,
            bbox={
                "boxstyle": "round,pad=0.31,rounding_size=0.03",
                "facecolor": "#ffffff",
                "edgecolor": "#d3d8de",
                "linewidth": 1.0,
            },
        )
    ax.text(
        0.5,
        0.055,
        (
            r"Persistent mode: $p \geq 0.5$; "
            r"$C_{ref}=N_{ov}/N_{ref}$; "
            r"$P_a=N_{ov}/N_a$; "
            r"$R_D^{plan}=D^{plan}_{s\to ref}/D^{plan}_{ref\to s}$."
        ),
        ha="center",
        va="center",
        fontsize=11.6,
        color="#4d5967",
        transform=ax.transAxes,
    )


def _trim_light_margin(image: np.ndarray, *, threshold: float = 0.985, pad: int = 18) -> np.ndarray:
    """Trim only the external near-white margin around a rendered figure."""
    rgb = image[..., :3]
    if rgb.dtype.kind in {"u", "i"}:
        rgb = rgb.astype(float) / 255.0
    non_white = np.any(rgb < threshold, axis=2)
    if image.shape[-1] == 4:
        alpha = image[..., 3]
        if alpha.dtype.kind in {"u", "i"}:
            alpha = alpha.astype(float) / 255.0
        non_white &= alpha > 0.05
    ys, xs = np.where(non_white)
    if ys.size == 0 or xs.size == 0:
        return image
    y0 = max(int(ys.min()) - pad, 0)
    y1 = min(int(ys.max()) + pad + 1, image.shape[0])
    x0 = max(int(xs.min()) - pad, 0)
    x1 = min(int(xs.max()) + pad + 1, image.shape[1])
    return image[y0:y1, x0:x1]


def _render_annotated_overlay(spec: SweepSpec, row: dict[str, object]) -> Path:
    variant_id = str(row["variant_id"])
    source = (
        spec.source_root
        / "run_figures"
        / variant_id
        / "simulated_active_network_reference_overlay.png"
    )
    if not source.exists():
        raise FileNotFoundError(f"Missing source overlay for {variant_id}: {source}")
    destination = spec.docs_dir / f"{variant_id}_reference_overlay.png"
    destination.parent.mkdir(parents=True, exist_ok=True)

    image = _trim_light_margin(mpimg.imread(source))
    image_aspect = image.shape[0] / image.shape[1]
    figure_width = 11.5
    image_height = figure_width * image_aspect
    band_height = 4.95
    fig = plt.figure(figsize=(figure_width, image_height + band_height), dpi=190)
    grid = fig.add_gridspec(2, 1, height_ratios=[image_height, band_height], hspace=0.02)
    image_ax = fig.add_subplot(grid[0])
    image_ax.imshow(image)
    image_ax.set_axis_off()
    band_ax = fig.add_subplot(grid[1])
    _render_metric_band(band_ax, row)
    fig.savefig(destination, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    return destination


def _series(rows: list[dict[str, object]], key: str) -> list[float]:
    return [_float({k: str(v) for k, v in row.items()}, key) for row in rows]


def _render_trend_graph(spec: SweepSpec, rows: list[dict[str, object]]) -> Path:
    destination = spec.docs_dir / "metric_trends.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    x_values = [float(row["K_m_s"]) for row in rows]
    labels = [_format_k(value) for value in x_values]

    fig, axes = plt.subplots(4, 1, figsize=(11.5, 12.1), dpi=190, sharex=True)
    fig.patch.set_facecolor("white")
    fig.suptitle(spec.title, fontsize=15, fontweight="bold", y=0.985)

    axes[0].plot(x_values, _series(rows, "active_cell_count"), "o-", color="#2878b5", label=r"$N_a$")
    axes[0].plot(
        x_values,
        _series(rows, "missing_network_cell_count"),
        "o-",
        color="#c44e52",
        label=r"$N_{miss}$",
    )
    axes[0].plot(
        x_values,
        _series(rows, "extra_active_cell_count"),
        "o-",
        color="#8172b2",
        label=r"$N_{extra}$",
    )
    axes[0].set_ylabel("Cell count")
    axes[0].set_title("Network support size")

    axes[1].plot(
        x_values,
        _series(rows, "network_coverage_ratio"),
        "o-",
        color="#55a868",
        label=r"$C_{ref}$",
    )
    axes[1].plot(
        x_values,
        _series(rows, "active_precision_ratio"),
        "o-",
        color="#4c72b0",
        label=r"$P_a$",
    )
    axes[1].plot(x_values, _series(rows, "cell_f1_ratio"), "o-", color="#dd8452", label=r"$F_1$")
    axes[1].set_ylim(0.0, 1.02)
    axes[1].set_ylabel("Ratio")
    axes[1].set_title("Overlap quality")

    axes[2].plot(
        x_values,
        _series(rows, "sim_to_network_distance_mean_m"),
        "o-",
        color="#d62728",
        label=r"$D^{plan}_{s\to ref}$",
    )
    axes[2].plot(
        x_values,
        _series(rows, "network_to_sim_distance_mean_m"),
        "o-",
        color="#9467bd",
        label=r"$D^{plan}_{ref\to s}$",
    )
    axes[2].plot(
        x_values,
        _series(rows, "bidirectional_distance_mean_m"),
        "o-",
        color="#1f77b4",
        label=r"$\bar{D}^{plan}$",
    )
    axes[2].set_ylabel("Distance (m)")
    axes[2].set_title("Planar distance diagnostics")

    log_balance = [_distance_log10_balance(row) for row in rows]
    axes[3].plot(
        x_values,
        log_balance,
        "o-",
        color="#2ca02c",
        label=r"$\log_{10} R_D^{plan}$",
    )
    axes[3].axhline(0.0, color="#444444", linestyle="--", linewidth=1.0, label="balance")
    axes[3].set_ylabel("Distance balance")
    axes[3].set_title("Planar distance balance proxy")
    axes[3].set_xlabel(r"Hydraulic conductivity $K$ (m/s)")

    for ax in axes:
        ax.set_xscale("log")
        ax.grid(True, which="major", color="#d9dde2", linewidth=0.8)
        ax.grid(True, which="minor", color="#eef0f3", linewidth=0.45)
        ax.legend(loc="best", frameon=True, framealpha=0.92)
        for x in x_values:
            ax.axvline(x, color="#edf0f2", linewidth=0.6, zorder=0)
    axes[3].set_xticks(x_values, labels)
    fig.text(
        0.5,
        0.018,
        (
            r"$N_a$ active simulated cells; $N_{miss}$ reference cells not captured; "
            r"$N_{extra}$ active cells outside reference; "
            r"$C_{ref}$ coverage; $P_a$ precision; $F_1$ harmonic score; "
            r"$R_D^{plan}=D^{plan}_{s\to ref}/D^{plan}_{ref\to s}$."
        ),
        ha="center",
        fontsize=8.6,
        color="#4d5967",
    )
    fig.tight_layout(rect=(0.035, 0.045, 0.995, 0.965))
    fig.savefig(destination, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    return destination


def _render_tradeoff_graph(spec: SweepSpec, rows: list[dict[str, object]]) -> Path:
    destination = spec.docs_dir / "metric_tradeoff.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    k_values = np.asarray([float(row["K_m_s"]) for row in rows], dtype="float64")
    log_k = np.log10(k_values)
    labels = [str(row["variant_id"]) for row in rows]
    active_counts = np.asarray(_series(rows, "active_cell_count"), dtype="float64")
    sizes = 80.0 + 320.0 * active_counts / max(float(np.nanmax(active_counts)), 1.0)

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.9), dpi=190)
    fig.patch.set_facecolor("white")
    fig.suptitle(f"{spec.title} - overlap and distance tradeoffs", fontsize=14, fontweight="bold")

    coverage = np.asarray(_series(rows, "network_coverage_ratio"), dtype="float64")
    precision = np.asarray(_series(rows, "active_precision_ratio"), dtype="float64")
    scatter = axes[0].scatter(
        coverage,
        precision,
        c=log_k,
        s=sizes,
        cmap="viridis",
        edgecolor="#203040",
        linewidth=0.7,
        alpha=0.92,
    )
    axes[0].set_xlabel(r"Reference coverage $C_{ref}$")
    axes[0].set_ylabel(r"Active precision $P_a$")
    axes[0].set_title("Overlap tradeoff")
    axes[0].set_xlim(0.0, min(1.0, max(0.2, float(np.nanmax(coverage)) + 0.15)))
    axes[0].set_ylim(0.0, min(1.0, max(0.2, float(np.nanmax(precision)) + 0.15)))
    for x, y, label in zip(coverage, precision, labels, strict=True):
        axes[0].annotate(label, (x, y), xytext=(5, 4), textcoords="offset points", fontsize=8)

    bidirectional = np.asarray(_series(rows, "bidirectional_distance_mean_m"), dtype="float64")
    f1 = np.asarray(_series(rows, "cell_f1_ratio"), dtype="float64")
    axes[1].scatter(
        bidirectional,
        f1,
        c=log_k,
        s=sizes,
        cmap="viridis",
        edgecolor="#203040",
        linewidth=0.7,
        alpha=0.92,
    )
    axes[1].set_xlabel(r"Planar bidirectional distance $\bar{D}^{plan}$ (m)")
    axes[1].set_ylabel(r"Overlap score $F_1$")
    axes[1].set_title("Distance vs overlap quality")
    axes[1].set_xlim(0.0, max(100.0, float(np.nanmax(bidirectional)) * 1.28))
    axes[1].set_ylim(0.0, min(1.0, max(0.2, float(np.nanmax(f1)) + 0.15)))
    for x, y, label in zip(bidirectional, f1, labels, strict=True):
        axes[1].annotate(label, (x, y), xytext=(5, 4), textcoords="offset points", fontsize=8)

    for ax in axes:
        ax.grid(True, color="#d9dde2", linewidth=0.8)
        ax.set_axisbelow(True)

    cbar = fig.colorbar(scatter, ax=axes.ravel().tolist(), fraction=0.035, pad=0.025)
    cbar.set_label(r"$\log_{10}(K)$, K in m/s")
    fig.text(
        0.5,
        0.015,
        "Point size is proportional to the number of persistent simulated-active cells.",
        ha="center",
        fontsize=8.8,
        color="#4d5967",
    )
    fig.subplots_adjust(left=0.075, right=0.89, bottom=0.14, top=0.84, wspace=0.32)
    fig.savefig(destination, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    return destination


def _copy_case_configuration(spec: SweepSpec) -> Path:
    source = spec.source_root / "comparison_figures" / "case_configuration.png"
    if not source.exists():
        raise FileNotFoundError(f"Missing case configuration figure: {source}")
    destination = spec.docs_dir / "case_configuration.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def render_sweep(spec: SweepSpec) -> list[Path]:
    rows = _merged_metrics(spec)
    if not rows:
        raise RuntimeError(f"No metric rows found for {spec.name}")
    written = [_copy_case_configuration(spec)]
    written.extend(_render_annotated_overlay(spec, row) for row in rows)
    written.append(_render_trend_graph(spec, rows))
    written.append(_render_tradeoff_graph(spec, rows))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sweep",
        choices=("all", "wide", "extreme"),
        default="all",
        help="Select which committed Nancon K-sweep asset set to render.",
    )
    args = parser.parse_args()

    selected = [spec for spec in SWEEPS if args.sweep in ("all", spec.name)]
    for spec in selected:
        written = render_sweep(spec)
        print(f"{spec.name}: wrote {len(written)} figure(s)")
        for path in written:
            print(f"  {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
