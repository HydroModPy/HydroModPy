"""Objective-function figures: parameter maps and sensitivity cuts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.calibration.reporting.network_transient import io as _nt_io
from hydromodpy.calibration.reporting.network_transient.geometry import _candidate_is_truth

_read_json = _nt_io.read_json
_float = _nt_io.coerce_float


def _save_objective_parameter_maps(
    truth_dir: Path | None, score_rows: list[dict[str, str]], path: Path
) -> None:
    rows = [
        row
        for row in score_rows
        if row.get("status") == "completed"
        and np.isfinite(_float(row.get("mK")))
        and np.isfinite(_float(row.get("Sy")))
    ]
    if not rows:
        return
    target = _truth_parameters(truth_dir)
    best_candidates = [row for row in rows if not _candidate_is_truth(row)] or rows
    best = min(best_candidates, key=lambda row: _float(row.get("J"), float("inf")))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    specs = (
        ("C_debit_phys", "Objectif flux"),
        ("C_reseau_phys", "Objectif affleurements"),
        ("J", "Objectif combine"),
    )
    x = np.asarray([_float(row.get("mK")) for row in rows], dtype=float)
    y = np.asarray([_float(row.get("Sy")) for row in rows], dtype=float)
    xmin, xmax = _axis_bounds(x)
    ymin, ymax = _axis_bounds(y)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(14.0, 4.4), dpi=150, sharex=True, sharey=True)
    dense_grid = len(rows) > 80
    point_size = 18 if dense_grid else (70 if len(rows) > 12 else 110)
    for ax, (column, title) in zip(axes, specs, strict=False):
        values = np.asarray([_float(row.get(column)) for row in rows], dtype=float)
        plot_values, floor = _log_objective_values(values)
        finite_plot = plot_values[np.isfinite(plot_values)]
        norm = None
        if finite_plot.size and float(np.nanmax(finite_plot)) > floor:
            norm = LogNorm(vmin=floor, vmax=float(np.nanmax(finite_plot)))
        image = _objective_grid_image(ax, x, y, plot_values, norm=norm)
        scatter = ax.scatter(
            x,
            y,
            c=plot_values,
            s=point_size,
            cmap="viridis",
            norm=norm,
            edgecolors="#17202a",
            linewidths=0.18 if dense_grid else 0.6,
            alpha=0.72 if dense_grid else 1.0,
            zorder=3,
        )
        if not dense_grid:
            for xi, yi, value in zip(x, y, values, strict=False):
                if np.isfinite(value):
                    ax.text(
                        xi,
                        yi,
                        f"{value:.2g}",
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="white",
                    )
        if target is not None:
            ax.scatter(
                [target[0]],
                [target[1]],
                marker="*",
                s=210,
                color="#f2c94c",
                edgecolors="#17202a",
                linewidths=0.9,
                label="valeur cible",
                zorder=5,
            )
        ax.scatter(
            [_float(best.get("mK"))],
            [_float(best.get("Sy"))],
            marker="o",
            s=240,
            facecolors="none",
            edgecolors="#c43b2f",
            linewidths=2.3,
            label="meilleur candidat non cible",
            zorder=4,
        )
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_title(title)
        ax.set_xlabel("mK")
        ax.grid(True, ls=":", lw=0.45, color="#cfd8df")
        mappable = image if image is not None else scatter
        fig.colorbar(mappable, ax=ax, fraction=0.046, pad=0.04, label=f"{column} (log)")
    axes[0].set_ylabel("Sy")
    axes[-1].legend(loc="best", fontsize=9)
    fig.suptitle("Fonction objectif en fonction des parametres")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _save_objective_profile_cuts(
    truth_dir: Path | None, score_rows: list[dict[str, str]], path: Path
) -> None:
    rows = [
        row
        for row in score_rows
        if row.get("status") == "completed"
        and np.isfinite(_float(row.get("mK")))
        and np.isfinite(_float(row.get("Sy")))
    ]
    target = _truth_parameters(truth_dir)
    if not rows or target is None:
        return
    mk_target, sy_target = target
    mk_values = np.asarray([_float(row.get("mK")) for row in rows], dtype=float)
    sy_values = np.asarray([_float(row.get("Sy")) for row in rows], dtype=float)
    mk_cut_value = _nearest_value(mk_values, mk_target)
    sy_cut_value = _nearest_value(sy_values, sy_target)
    mk_cut = sorted(
        [row for row in rows if np.isclose(_float(row.get("mK")), mk_cut_value)],
        key=lambda row: _float(row.get("Sy")),
    )
    sy_cut = sorted(
        [row for row in rows if np.isclose(_float(row.get("Sy")), sy_cut_value)],
        key=lambda row: _float(row.get("mK")),
    )
    if len(mk_cut) < 2 and len(sy_cut) < 2:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.2), dpi=150)
    _plot_objective_cut(
        axes[0],
        mk_cut,
        x_key="Sy",
        target_value=sy_target,
        title=f"Coupe en Sy a mK={mk_cut_value:.3g}",
        xlabel="Sy",
    )
    _plot_objective_cut(
        axes[1],
        sy_cut,
        x_key="mK",
        target_value=mk_target,
        title=f"Coupe en mK a Sy={sy_cut_value:.3g}",
        xlabel="mK",
    )
    fig.suptitle("Coupes de sensibilite de la fonction objectif")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _nearest_value(values: np.ndarray, target: float) -> float:
    finite = np.asarray(values[np.isfinite(values)], dtype=float)
    if finite.size == 0:
        return float("nan")
    return float(finite[np.argmin(np.abs(finite - target))])


def _plot_objective_cut(
    ax: Any,
    rows: list[dict[str, str]],
    *,
    x_key: str,
    target_value: float,
    title: str,
    xlabel: str,
) -> None:
    if len(rows) < 2:
        ax.text(0.5, 0.5, "coupe indisponible", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return
    x = np.asarray([_float(row.get(x_key)) for row in rows], dtype=float)
    curves = (
        ("J", "objectif combine", "#17202a", 2.2),
        ("C_debit_phys", "flux", "#c43b2f", 1.7),
        ("C_reseau_phys", "reseau", "#2662a5", 1.7),
    )
    for column, label, color, width in curves:
        raw_values = np.asarray([_float(row.get(column)) for row in rows], dtype=float)
        if not np.any(np.isfinite(raw_values) & (raw_values > 0.0)):
            continue
        values, _ = _log_objective_values(raw_values)
        ax.plot(x, values, marker="o", ms=3.0, lw=width, color=color, label=label)
    ax.axvline(target_value, color="#f2c94c", lw=1.5, ls="--", label="cible")
    ax.set_yscale("log")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Cout normalise (log)")
    ax.grid(True, which="both", ls=":", lw=0.45, color="#cfd8df")
    ax.legend(loc="best", fontsize=9)


def _log_objective_values(values: np.ndarray) -> tuple[np.ndarray, float]:
    finite_positive = values[np.isfinite(values) & (values > 0.0)]
    if finite_positive.size:
        floor = max(float(np.nanmin(finite_positive)) * 0.5, 1.0e-12)
        ceiling = float(np.nanmax(finite_positive))
    else:
        floor = 1.0e-12
        ceiling = 1.0
    plot_values = np.asarray(values, dtype=float).copy()
    plot_values[~np.isfinite(plot_values)] = np.nan
    plot_values[np.isfinite(plot_values) & (plot_values <= 0.0)] = floor
    if np.isfinite(plot_values).any():
        plot_values = np.minimum(plot_values, max(ceiling, floor))
    return plot_values, floor


def _objective_grid_image(
    ax: Any, x: np.ndarray, y: np.ndarray, values: np.ndarray, *, norm: Any = None
) -> Any:
    x_unique = np.asarray(sorted(set(float(v) for v in x if np.isfinite(v))), dtype=float)
    y_unique = np.asarray(sorted(set(float(v) for v in y if np.isfinite(v))), dtype=float)
    if x_unique.size < 2 or y_unique.size < 2:
        return None
    grid = np.full((y_unique.size, x_unique.size), np.nan, dtype=float)
    for xi, yi, value in zip(x, y, values, strict=False):
        if not np.isfinite(value):
            continue
        ix = int(np.argmin(np.abs(x_unique - xi)))
        iy = int(np.argmin(np.abs(y_unique - yi)))
        grid[iy, ix] = value
    if np.isfinite(grid).sum() < 4:
        return None
    dx = float(np.min(np.diff(x_unique))) if x_unique.size > 1 else 0.05
    dy = float(np.min(np.diff(y_unique))) if y_unique.size > 1 else 0.01
    masked = np.ma.masked_invalid(grid)
    return ax.imshow(
        masked,
        extent=[
            float(x_unique.min() - 0.5 * dx),
            float(x_unique.max() + 0.5 * dx),
            float(y_unique.min() - 0.5 * dy),
            float(y_unique.max() + 0.5 * dy),
        ],
        origin="lower",
        aspect="auto",
        cmap="viridis",
        norm=norm,
        alpha=0.82,
        zorder=1,
    )


def _truth_parameters(truth_dir: Path | None) -> tuple[float, float] | None:
    if truth_dir is None:
        return None
    metadata = _read_json(truth_dir / "metadata.json")
    mk = _float(metadata.get("mK_true"))
    sy = _float(metadata.get("Sy_true"))
    if np.isfinite(mk) and np.isfinite(sy):
        return mk, sy
    return None


def _best_completed_candidate_id(score_rows: list[dict[str, str]]) -> str | None:
    completed = [
        row
        for row in score_rows
        if row.get("status") == "completed" and not _candidate_is_truth(row)
    ]
    if not completed:
        completed = [row for row in score_rows if row.get("status") == "completed"]
    if not completed:
        return None
    best = min(completed, key=lambda row: _float(row.get("J"), float("inf")))
    return str(best.get("candidate_id", ""))


def _axis_bounds(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    vmin = float(finite.min())
    vmax = float(finite.max())
    if np.isclose(vmin, vmax):
        margin = max(abs(vmin) * 0.15, 0.05)
        return vmin - margin, vmax + margin
    margin = 0.12 * (vmax - vmin)
    return vmin - margin, vmax + margin
