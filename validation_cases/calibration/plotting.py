"""Suite-level plotting helpers for calibration twin benchmarks."""

from __future__ import annotations

from pathlib import Path


def _try_import_matplotlib():
    """Import matplotlib lazily and return pyplot, or None when unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    return plt


def _sanitize_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop rows lacking the minimal metrics used by suite figures."""
    return [
        row
        for row in rows
        if row.get("case_id") is not None and row.get("method_name") is not None
    ]


def write_suite_figures(
    method_rows: list[dict[str, object]],
    *,
    output_root: Path | None,
    figure_format: str = "png",
) -> tuple[Path, ...]:
    """Write suite-level figures and return the generated paths."""
    if output_root is None:
        return ()
    rows = _sanitize_rows(method_rows)
    if not rows:
        return ()
    plt = _try_import_matplotlib()
    if plt is None:
        return ()
    output_root.mkdir(parents=True, exist_ok=True)
    extension = str(figure_format).strip().lower() or "png"
    figure_paths = []

    labels = [
        f"{row['case_id']} | {row['method_name']}"
        for row in rows
    ]
    target_success = [float(row.get("target_success_rate") or 0.0) for row in rows]
    best_fit = [float(row.get("best_fit_rate") or 0.0) for row in rows]
    mean_cost = [row.get("mean_cost_best") for row in rows]
    mean_eval = [row.get("mean_n_evaluations") for row in rows]
    mean_time_per_eval = [row.get("mean_time_per_evaluation_seconds") for row in rows]

    fig, ax = plt.subplots(figsize=(12, max(4, 0.45 * len(rows) + 1)))
    y_positions = list(range(len(rows)))
    ax.barh(y_positions, best_fit, color="#9db5c9", label="best_fit_rate")
    ax.barh(y_positions, target_success, color="#284b63", alpha=0.85, label="target_success_rate")
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels)
    ax.set_xlim(0.0, 1.0)
    ax.set_xlabel("Success Rate")
    ax.set_title("Calibration Benchmark Success Rates")
    ax.legend()
    fig.tight_layout()
    path = output_root / f"benchmark_target_success_rates.{extension}"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    figure_paths.append(path)

    scatter_points = [
        (
            float(eval_count),
            float(cost),
            f"{row['case_id']} | {row['method_name']}",
        )
        for row, eval_count, cost in zip(rows, mean_eval, mean_cost, strict=False)
        if eval_count is not None and cost is not None and float(cost) > 0.0
    ]
    if scatter_points:
        fig, ax = plt.subplots(figsize=(8, 6))
        xs = [item[0] for item in scatter_points]
        ys = [item[1] for item in scatter_points]
        ax.scatter(xs, ys, color="#284b63")
        for x_value, y_value, label in scatter_points:
            ax.annotate(label, (x_value, y_value), fontsize=8)
        ax.set_xlabel("Mean Evaluations")
        ax.set_ylabel("Mean Best Cost")
        ax.set_yscale("log")
        ax.set_title("Cost vs Evaluation Budget")
        fig.tight_layout()
        path = output_root / f"benchmark_cost_vs_budget.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)

    time_points = [
        (
            float(time_value),
            float(cost),
            f"{row['case_id']} | {row['method_name']}",
        )
        for row, time_value, cost in zip(rows, mean_time_per_eval, mean_cost, strict=False)
        if time_value is not None and cost is not None and float(cost) > 0.0 and float(time_value) > 0.0
    ]
    if time_points:
        fig, ax = plt.subplots(figsize=(8, 6))
        xs = [item[0] for item in time_points]
        ys = [item[1] for item in time_points]
        ax.scatter(xs, ys, color="#3c6e71")
        for x_value, y_value, label in time_points:
            ax.annotate(label, (x_value, y_value), fontsize=8)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Mean Time per Evaluation (s)")
        ax.set_ylabel("Mean Best Cost")
        ax.set_title("Cost vs Time per Evaluation")
        fig.tight_layout()
        path = output_root / f"benchmark_time_vs_cost.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)

    normalized_error_points = []
    for row in rows:
        ratio_values = [
            float(value)
            for key, value in row.items()
            if str(key).startswith("mean_param_abs_error_over_tol__") and value is not None
        ]
        if ratio_values:
            normalized_error_points.append(
                (
                    float(sum(ratio_values) / len(ratio_values)),
                    f"{row['case_id']} | {row['method_name']}",
                )
            )
    if normalized_error_points:
        fig, ax = plt.subplots(figsize=(12, max(4, 0.4 * len(normalized_error_points) + 1)))
        y_positions = list(range(len(normalized_error_points)))
        values = [item[0] for item in normalized_error_points]
        labels = [item[1] for item in normalized_error_points]
        ax.barh(y_positions, values, color="#d9bf77")
        ax.axvline(1.0, color="#7a5c00", linestyle="--", linewidth=1.2)
        ax.set_yticks(y_positions)
        ax.set_yticklabels(labels)
        ax.set_xlabel("Mean Parameter Absolute Error / Tolerance")
        ax.set_title("Normalized Parameter Error")
        fig.tight_layout()
        path = output_root / f"benchmark_parameter_error_ratio.{extension}"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figure_paths.append(path)

    return tuple(figure_paths)
