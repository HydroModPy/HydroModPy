"""
Shared visualization helpers for calibration examples.

The helpers in this module are parameter-dimension agnostic and keep dedicated
views for 1D and 2D parameter spaces.
"""

from __future__ import annotations

import numpy as np


def unique_rows_with_counts(samples, decimals=10):
    """
    Aggregate duplicated sample rows after rounding.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Unique rows and their occurrence counts.
    """
    arr = np.asarray(samples, dtype=float)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return np.empty((0, 0), dtype=float), np.empty(0, dtype=int)
    rounded = np.round(arr, int(decimals))
    unique_rows, counts = np.unique(rounded, axis=0, return_counts=True)
    return unique_rows, counts


def select_representative_posterior_vectors(samples, n_vectors=10):
    """
    Select representative parameter vectors from posterior samples.

    Samples are projected onto their first principal direction and sampled at
    evenly spaced quantiles to keep a diverse set of trajectories.
    """
    arr = np.asarray(samples, dtype=float)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return np.empty((0, 0), dtype=float)

    n_keep = int(min(max(1, n_vectors), arr.shape[0]))
    if n_keep == arr.shape[0]:
        return arr.copy()

    centered = arr - np.mean(arr, axis=0, keepdims=True)
    if np.allclose(centered, 0.0):
        indices = np.linspace(0, arr.shape[0] - 1, n_keep, dtype=int)
        return arr[indices]

    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    axis_1 = vt[0]
    scores = centered @ axis_1
    order = np.argsort(scores)
    quantile_idx = np.linspace(0, arr.shape[0] - 1, n_keep, dtype=int)
    chosen = order[quantile_idx]
    return arr[chosen]


def build_posterior_quantile_lines(
    posterior_samples,
    parameter_names,
    quantiles=(0.05, 0.50, 0.95),
    fmt=".4g",
):
    """
    Format quantile lines for each parameter in posterior samples.
    """
    arr = np.asarray(posterior_samples, dtype=float)
    names = tuple(parameter_names)
    if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[1] != len(names):
        return []

    q = np.asarray(quantiles, dtype=float).ravel()
    if q.size != 3:
        raise ValueError("quantiles must contain exactly three values")

    q_labels = [f"q{int(round(v * 100)):02d}" for v in q]
    lines = []
    for idx, name in enumerate(names):
        values = np.quantile(arr[:, idx], q)
        lines.append(
            f"{name} {q_labels[0]}/{q_labels[1]}/{q_labels[2]} = "
            f"{values[0]:{fmt}}/{values[1]:{fmt}}/{values[2]:{fmt}}"
        )
    return lines


def build_parameter_summary_lines(
    params_true,
    params_best,
    parameter_names,
    *,
    default_fmt=".4g",
    format_overrides=None,
):
    """
    Format one summary line per calibrated parameter.
    """
    params_true = {} if params_true is None else dict(params_true)
    params_best = {} if params_best is None else dict(params_best)
    overrides = {} if format_overrides is None else dict(format_overrides)

    lines = []
    for name in tuple(parameter_names):
        fmt = str(overrides.get(name, default_fmt))
        true_value = float(params_true.get(name, np.nan))
        best_value = float(params_best.get(name, np.nan))
        lines.append(
            f"{name} true={true_value:{fmt}}   {name} hat={best_value:{fmt}}"
        )
    return lines


def build_posterior_summary_lines(
    result_view,
    *,
    parameter_names,
    quantiles=(0.05, 0.50, 0.95),
    fmt=".4g",
):
    """
    Build posterior/chain summary lines from a result-view dictionary.
    """
    if not result_view.get("has_posterior", False):
        return ["No posterior sample distribution (deterministic method)."]

    posterior_unique = np.asarray(
        result_view.get("posterior_unique", np.empty((0, 0))),
        dtype=float,
    )
    chain_unique = np.asarray(
        result_view.get("chain_unique", np.empty((0, 0))),
        dtype=float,
    )
    posterior_samples = np.asarray(
        result_view.get("posterior_samples", np.empty((0, 0))),
        dtype=float,
    )

    lines = [
        f"Unique states: posterior={posterior_unique.shape[0]}  chain={chain_unique.shape[0]}"
    ]
    lines.extend(
        build_posterior_quantile_lines(
            posterior_samples=posterior_samples,
            parameter_names=parameter_names,
            quantiles=quantiles,
            fmt=fmt,
        )
    )
    return lines


def _is_strictly_positive(values):
    arr = np.asarray(values, dtype=float).ravel()
    finite = arr[np.isfinite(arr)]
    return bool(finite.size > 0 and np.all(finite > 0.0))


def _concat_vectors(*items):
    if not items:
        return np.empty(0, dtype=float)
    vectors = [np.asarray(item, dtype=float).ravel() for item in items]
    if not vectors:
        return np.empty(0, dtype=float)
    return np.concatenate(vectors)


def apply_parameter_axis_scales(
    ax,
    sample_source,
    parameter_names,
    *,
    params_true=None,
    params_best=None,
    force_log_parameter_names=(),
    auto_log_if_positive=True,
):
    """
    Apply log scaling on parameter-panel axes when data supports it.

    `force_log_parameter_names` can be used for known strictly-positive
    parameters that should always be shown on log scale (example: `K`).
    """
    arr = np.asarray(sample_source, dtype=float)
    names = tuple(parameter_names)
    if arr.ndim != 2 or arr.shape[1] != len(names) or len(names) == 0:
        return

    true_map = {} if params_true is None else dict(params_true)
    best_map = {} if params_best is None else dict(params_best)
    force_log = {str(name) for name in tuple(force_log_parameter_names)}

    def _axis_values(index, name):
        return _concat_vectors(
            arr[:, index],
            [true_map.get(name, np.nan)],
            [best_map.get(name, np.nan)],
        )

    def _should_use_log_scale(name, values):
        return (name in force_log) or (
            bool(auto_log_if_positive) and _is_strictly_positive(values)
        )

    if len(names) == 1:
        name = names[0]
        values = _axis_values(0, name)
        if _should_use_log_scale(name, values):
            ax.set_xscale("log")
        return

    if len(names) == 2:
        x_name, y_name = names
        x_values = _axis_values(0, x_name)
        y_values = _axis_values(1, y_name)
        if _should_use_log_scale(x_name, x_values):
            ax.set_xscale("log")
        if _should_use_log_scale(y_name, y_values):
            ax.set_yscale("log")
        return

    if bool(auto_log_if_positive) and _is_strictly_positive(arr):
        ax.set_yscale("log")


def _vector_from_mapping(mapping, parameter_names):
    names = tuple(parameter_names)
    if mapping is None:
        return np.full(len(names), np.nan, dtype=float)
    return np.array([float(mapping.get(name, np.nan)) for name in names], dtype=float)


def plot_parameter_distribution(
    ax,
    sample_source,
    parameter_names,
    *,
    params_true=None,
    params_best=None,
    decimals=10,
):
    """
    Plot posterior parameter distribution for 1D, 2D, or higher dimensions.

    - 1 parameter: histogram + true/best markers
    - 2 parameters: scatter cloud + true/best markers
    - >2 parameters: boxplot marginals + true/best markers
    """
    arr = np.asarray(sample_source, dtype=float)
    names = tuple(parameter_names)
    n_params = len(names)
    if arr.ndim != 2 or arr.shape[0] == 0 or n_params == 0 or arr.shape[1] != n_params:
        ax.set_title("Parameter distribution")
        ax.text(0.5, 0.5, "No parameter samples", ha="center", va="center", transform=ax.transAxes)
        return

    true_vec = _vector_from_mapping(params_true, names)
    best_vec = _vector_from_mapping(params_best, names)
    has_true = np.isfinite(true_vec)
    has_best = np.isfinite(best_vec)

    if n_params == 1:
        values = arr[:, 0]
        n_bins = int(min(40, max(10, np.sqrt(values.size))))
        ax.hist(values, bins=n_bins, color="tab:gray", alpha=0.70, edgecolor="white", linewidth=0.5)
        if has_true[0]:
            ax.axvline(true_vec[0], color="tab:blue", linewidth=1.6, label="True")
        if has_best[0]:
            ax.axvline(best_vec[0], color="tab:red", linewidth=1.6, linestyle="--", label="Best/MAP")
        ax.set_xlabel(names[0])
        ax.set_ylabel("Frequency")
        ax.set_title("Parameter distribution (1D)")
        ax.grid(True, ls=":", alpha=0.35)
        if np.any(has_true) or np.any(has_best):
            ax.legend(loc="best")
        return

    if n_params == 2:
        points, counts = unique_rows_with_counts(arr, decimals=decimals)
        if points.shape[0] > 0:
            size_scale = 30.0 if counts.size == 0 else 20.0 + 120.0 * (counts / np.max(counts)) ** 0.7
            ax.scatter(
                points[:, 0],
                points[:, 1],
                s=size_scale,
                alpha=0.70,
                color="tab:gray",
                edgecolors="white",
                linewidths=0.4,
                label="Sampled states",
                zorder=2,
            )
        if np.all(has_true):
            ax.scatter(
                [true_vec[0]],
                [true_vec[1]],
                s=70,
                facecolors="none",
                edgecolors="tab:blue",
                linewidths=1.6,
                label="True",
                zorder=3,
            )
        if np.all(has_best):
            ax.scatter(
                [best_vec[0]],
                [best_vec[1]],
                s=70,
                color="tab:red",
                marker="x",
                linewidths=1.8,
                label="Best/MAP",
                zorder=3,
            )
        ax.set_xlabel(names[0])
        ax.set_ylabel(names[1])
        ax.set_title("Parameter distribution (2D)")
        ax.grid(True, ls=":", alpha=0.35)
        ax.legend(loc="best")
        return

    data = [arr[:, i] for i in range(n_params)]
    positions = np.arange(1, n_params + 1, dtype=int)
    box = ax.boxplot(data, positions=positions, patch_artist=True, showfliers=False, widths=0.65)
    for patch in box["boxes"]:
        patch.set_facecolor("tab:gray")
        patch.set_alpha(0.35)

    if np.any(has_true):
        idx = positions[has_true]
        ax.scatter(idx, true_vec[has_true], s=45, facecolors="none", edgecolors="tab:blue", label="True", zorder=3)
    if np.any(has_best):
        idx = positions[has_best]
        ax.scatter(idx, best_vec[has_best], s=45, color="tab:red", marker="x", label="Best/MAP", zorder=3)

    ax.set_xticks(positions)
    ax.set_xticklabels(names, rotation=30, ha="right")
    ax.set_ylabel("Sample value")
    ax.set_title("Parameter marginals (>2D)")
    ax.grid(True, axis="y", ls=":", alpha=0.35)
    ax.legend(loc="best")
