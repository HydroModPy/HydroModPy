"""Build a compact HTML diagnostic page for the B0 real-run smoke outputs."""

from __future__ import annotations

import csv
import html
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.analysis.comparison.web.html_utils import link_relative, safe
from hydromodpy.calibration.network_transient_truth import (
    mesh_cell_geometry,
    q_total_release_from_drain_by_cell,
)
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.run import Run

ROOT = Path(__file__).resolve().parent
SOURCE_TRANSIENT_CONFIG = (
    REPO_ROOT
    / "examples"
    / "projects"
    / "10_testbed_workflow"
    / "boussinesq"
    / "natural_geology_k"
    / "base_site_01_mf6_bouss_transient.toml"
)
REAL_ROOT = ROOT / "outputs" / "real_runs"
WEB_ROOT = REAL_ROOT / "web"
FIGURE_ROOT = WEB_ROOT / "figures"
TRUTH_PACKAGE_CANDIDATES = (
    REAL_ROOT / "site_01_truth_package_mK_0p65",
    REAL_ROOT / "site_01_truth_package",
)
SCORE_TABLE_CANDIDATES = (
    REAL_ROOT / "site_01_candidate_scores_mK_0p65.csv",
    REAL_ROOT / "site_01_candidate_scores.csv",
)

RUN_ROOTS = {
    "mK_0p50": REAL_ROOT / "candidate_mK_0p50_Sy_0p05_steady_mf6",
    "mK_0p60": REAL_ROOT / "candidate_mK_0p60_Sy_0p05_steady_mf6",
    "mK_0p65": REAL_ROOT / "candidate_mK_0p65_Sy_0p05_steady_mf6",
    "mK_0p70": REAL_ROOT / "candidate_mK_0p70_Sy_0p05_steady_mf6",
    "mK_0p75": REAL_ROOT / "candidate_mK_0p75_Sy_0p05_steady_mf6",
    "mK_1p00": REAL_ROOT / "base_site_01_truth_steady_mf6",
    "mK_1p25": REAL_ROOT / "candidate_mK_1p25_Sy_0p08_steady_mf6",
}
MAP_LABELS = ("mK_0p50", "mK_0p65", "mK_1p00", "mK_1p25")


def main() -> None:
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    truth_dir = _first_existing(TRUTH_PACKAGE_CANDIDATES)
    score_table = _first_existing(SCORE_TABLE_CANDIDATES)
    k_rows = _read_csv(REAL_ROOT / "steady_mK_network_extent_summary.csv")
    score_rows = _read_csv(score_table) if score_table is not None else []
    normalization = _read_json(truth_dir / "normalization.json") if truth_dir is not None else {}
    truth_q = (
        _read_truth_discharge(truth_dir / "transient_q_total_release.csv")
        if truth_dir is not None
        else []
    )
    filtered_k_rows = [row for row in k_rows if _float(row.get("threshold_m3_s")) == 0.0]
    figures = _generate_figures(
        truth_dir=truth_dir,
        k_rows=filtered_k_rows,
        score_rows=score_rows,
        truth_q=truth_q,
    )

    html_text = _page(
        normalization=normalization,
        k_rows=filtered_k_rows,
        score_rows=score_rows,
        figures=figures,
        truth_dir=truth_dir,
        score_table=score_table,
    )
    out = WEB_ROOT / "index.html"
    out.write_text(html_text, encoding="utf-8")
    print(out)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _first_existing(paths: tuple[Path, ...]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _read_truth_discharge(path: Path) -> list[float]:
    rows = _read_csv(path)
    return [_float(row.get("q_total_release")) for row in rows]


def _float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: Any, digits: int = 4) -> str:
    val = _float(value)
    if not np.isfinite(val):
        return ""
    if abs(val) >= 1e4 or (abs(val) < 1e-3 and val != 0.0):
        return f"{val:.{digits}e}"
    return f"{val:.{digits}f}"


def _generate_figures(
    *,
    truth_dir: Path | None,
    k_rows: list[dict[str, str]],
    score_rows: list[dict[str, str]],
    truth_q: list[float],
) -> dict[str, Path]:
    figures: dict[str, Path] = {}
    figure_specs = (
        ("watershed_id_card", _save_watershed_id_card, (RUN_ROOTS["mK_0p65"],)),
        ("steady_balance_didactic", _save_steady_balance_didactic, (truth_dir, k_rows)),
        ("recharge_chronicle", _save_recharge_chronicle_figure, ()),
        ("outflow_drain_maps", _save_outflow_map_grid, (truth_dir, MAP_LABELS)),
        ("network_support_diagnostics", _save_network_support_diagnostics, (truth_dir, score_rows)),
        ("k_sweep_network_extent", _save_k_sweep_figure, (k_rows,)),
        ("q_total_release_timeseries", _save_q_timeseries_figure, (score_rows, truth_q)),
        ("score_components", _save_score_components_figure, (score_rows,)),
        ("objective_parameter_maps", _save_objective_parameter_maps, (truth_dir, score_rows)),
    )
    for name, writer, args in figure_specs:
        path = FIGURE_ROOT / f"{name}.png"
        try:
            writer(*args, path)
        except Exception:
            continue
        if path.is_file():
            figures[name] = path
    return figures


def _open_first_run(root: Path) -> tuple[SimulationCatalog, Run]:
    catalog = SimulationCatalog(root)
    try:
        sims = catalog.simulations
        if sims.empty:
            raise RuntimeError(f"no simulation in {root}")
        return catalog, Run.from_id(catalog, str(sims.iloc[0]["sim_id"]))
    except Exception:
        catalog.close()
        raise


def _save_watershed_id_card(root: Path, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from hydromodpy.display.figures.watershed_id_card import WatershedIdCardFigure

    path.parent.mkdir(parents=True, exist_ok=True)
    catalog, run = _open_first_run(root)
    try:
        fig = WatershedIdCardFigure().plot(run, save_path=path)
        plt.close(fig)
    finally:
        catalog.close()


def _save_water_budget(root: Path, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from hydromodpy.display.figures.water_budget import WaterBudget

    path.parent.mkdir(parents=True, exist_ok=True)
    catalog, run = _open_first_run(root)
    try:
        fig = WaterBudget().plot(run, save_path=path)
        plt.close(fig)
    finally:
        catalog.close()


def _save_steady_balance_didactic(truth_dir: Path | None, rows: list[dict[str, str]], path: Path) -> None:
    if truth_dir is None:
        return
    normalization = _read_json(truth_dir / "normalization.json")
    q_ref = _float(normalization.get("Q_ref_steady"))
    if not np.isfinite(q_ref):
        return

    sweep = [
        (
            _float(row.get("mK")),
            _float(row.get("q_total_m3_s")),
            _float(row.get("active_fraction")) * 100.0,
        )
        for row in rows
    ]
    sweep = [item for item in sweep if all(np.isfinite(value) for value in item)]
    sweep.sort(key=lambda item: item[0])

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.4), dpi=150)

    ax = axes[0]
    ax.barh(
        ["entree recharge moyenne", "sortie Q_total_release"],
        [q_ref, q_ref],
        color=["#2f8f46", "#c45a2a"],
        alpha=0.82,
    )
    ax.set_xlabel("Flux steady (m3/s)")
    ax.set_title("Fermeture du permanent cible")
    ax.grid(True, axis="x", ls=":", lw=0.45, color="#cfd8df")
    ax.text(
        0.02,
        -0.34,
        "Le bilan steady fixe surtout le total. Le signal de calibration reseau vient de la repartition spatiale.",
        transform=ax.transAxes,
        fontsize=9,
        color="#5d6875",
    )

    ax = axes[1]
    if sweep:
        x = np.asarray([item[0] for item in sweep], dtype=float)
        q = np.asarray([item[1] for item in sweep], dtype=float)
        active = np.asarray([item[2] for item in sweep], dtype=float)
        ax.plot(x, q / q_ref, marker="o", color="#17202a", lw=1.6, label="Q_total / Q_ref")
        ax2 = ax.twinx()
        ax2.plot(x, active, marker="s", color="#b5413c", lw=1.6, label="cellules actives")
        ax.axvline(0.65, color="#2662a5", ls="--", lw=1.1, label="mK cible")
        ax.set_xlabel("mK")
        ax.set_ylabel("Q_total / Q_ref")
        ax2.set_ylabel("Cellules actives (%)")
        ax.set_title("Pourquoi le budget seul ne suffit pas")
        ax.grid(True, ls=":", lw=0.45, color="#cfd8df")
        handles, labels = ax.get_legend_handles_labels()
        handles2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(handles + handles2, labels + labels2, loc="best", fontsize=9)
    else:
        ax.text(0.5, 0.5, "balayage K absent", ha="center", va="center", transform=ax.transAxes)

    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _save_recharge_chronicle_figure(path: Path) -> None:
    values = _recharge_values_from_config()
    if values.size == 0:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = np.arange(1, values.size + 1)
    mean_value = float(np.nanmean(values))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9.0, 3.8), dpi=150)
    ax.bar(x, values, color="#2f8f46", alpha=0.78, width=0.74, label="recharge mensuelle")
    ax.axhline(mean_value, color="#17202a", lw=1.4, ls="--", label=f"moyenne {mean_value:.3g} mm/j")
    ax.set_title("Chronique de recharge synthetique imposee")
    ax.set_xlabel("Mois de simulation")
    ax.set_ylabel("Recharge (mm/j)")
    ax.grid(True, axis="y", ls=":", lw=0.45, color="#cfd8df")
    ax.legend(loc="best", fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _recharge_values_from_config() -> np.ndarray:
    cfg = _read_toml(SOURCE_TRANSIENT_CONFIG)
    data = cfg.get("data", {}) if isinstance(cfg.get("data"), dict) else {}
    recharge = data.get("recharge", {}) if isinstance(data.get("recharge"), dict) else {}
    sources = recharge.get("sources", [])
    if not sources:
        return np.asarray([], dtype=float)
    values = sources[0].get("values", []) if isinstance(sources[0], dict) else []
    return np.asarray(values, dtype=float).reshape(-1)


def _save_k_sweep_figure(rows: list[dict[str, str]], path: Path) -> None:
    data = [
        (
            _float(row.get("mK")),
            _float(row.get("active_fraction")) * 100.0,
            _float(row.get("equivalent_length_m")),
            _float(row.get("q_total_m3_s")),
        )
        for row in rows
    ]
    data = [
        item for item in data if all(np.isfinite(value) for value in item[:3]) and item[0] > 0.0
    ]
    if not data:
        return
    data.sort(key=lambda item: item[0])
    x = np.asarray([item[0] for item in data], dtype=float)
    active = np.asarray([item[1] for item in data], dtype=float)
    length = np.asarray([item[2] for item in data], dtype=float)
    q_total = np.asarray([item[3] for item in data], dtype=float)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(8.2, 7.4), dpi=150, sharex=True)
    axes[0].plot(x, active, marker="o", color="#b5413c", lw=1.8)
    axes[0].axvline(0.65, color="#17202a", lw=1.0, ls="--", label="mK=0.65")
    axes[0].set_ylabel("Cellules actives (%)")
    axes[0].legend(loc="best", fontsize=8)

    axes[1].plot(x, length, marker="o", color="#2662a5", lw=1.8)
    axes[1].set_ylabel("Longueur equiv. (m)")

    axes[2].plot(x, q_total, marker="o", color="#26826a", lw=1.8)
    axes[2].set_ylabel("Q total (m3/s)")
    axes[2].set_xlabel("Multiplicateur K")

    for ax in axes:
        ax.grid(True, ls=":", lw=0.45, color="#cfd8df")
    fig.suptitle("Balayage steady K - extension du drainage actif")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _save_q_timeseries_figure(
    score_rows: list[dict[str, str]], truth_q: list[float], path: Path
) -> None:
    series = _q_total_release_series(score_rows=score_rows, truth_q=truth_q)
    if not series:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9.0, 4.6), dpi=150)
    items = list(series.items())
    for idx, (name, values) in enumerate(items):
        arr = np.asarray(values, dtype=float)
        if arr.size == 0:
            continue
        is_reference = idx == 0
        ax.plot(
            np.arange(arr.size),
            arr,
            marker="o" if is_reference else None,
            ms=3.2 if is_reference else 0.0,
            lw=2.4 if is_reference else 1.0,
            color="#17202a" if is_reference else "#9aa4af",
            alpha=1.0 if is_reference else 0.42,
            zorder=4 if is_reference else 2,
            label=name,
        )
    ax.set_title("Chronique mensuelle Q_total_release")
    ax.set_xlabel("Periode mensuelle")
    ax.set_ylabel("Q_total_release (m3/s)")
    ax.grid(True, ls=":", lw=0.45, color="#cfd8df")
    ax.legend(loc="best", fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _save_score_components_figure(score_rows: list[dict[str, str]], path: Path) -> None:
    rows = [row for row in score_rows if row.get("candidate_id") != "truth_identity"]
    if not rows:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [str(row.get("candidate_id", "")) for row in rows]
    network = np.asarray([_float(row.get("C_reseau_phys")) for row in rows], dtype=float)
    discharge = np.asarray([_float(row.get("C_debit_phys")) for row in rows], dtype=float)
    x = np.arange(len(rows))
    width = 0.34

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    ax.bar(x - width / 2, network, width, color="#2662a5", label="C_reseau_phys")
    ax.bar(x + width / 2, discharge, width, color="#b66a1f", label="C_debit_phys")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_ylabel("Cout normalise")
    ax.set_title("Contribution des deux termes de calibration")
    ax.grid(True, axis="y", ls=":", lw=0.45, color="#cfd8df")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


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
    best = min(rows, key=lambda row: _float(row.get("J"), float("inf")))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    specs = (
        ("C_debit_phys", "Objectif flux", "#2662a5"),
        ("C_reseau_phys", "Objectif affleurements", "#b66a1f"),
        ("J", "Objectif combine", "#7b4fa1"),
    )
    x = np.asarray([_float(row.get("mK")) for row in rows], dtype=float)
    y = np.asarray([_float(row.get("Sy")) for row in rows], dtype=float)
    xmin, xmax = _axis_bounds(x)
    ymin, ymax = _axis_bounds(y)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(14.0, 4.4), dpi=150, sharex=True, sharey=True)
    for ax, (column, title, color) in zip(axes, specs, strict=False):
        values = np.asarray([_float(row.get(column)) for row in rows], dtype=float)
        scatter = ax.scatter(
            x,
            y,
            c=values,
            s=110,
            cmap="viridis",
            edgecolors="#17202a",
            linewidths=0.6,
            zorder=3,
        )
        for xi, yi, value in zip(x, y, values, strict=False):
            if np.isfinite(value):
                ax.text(xi, yi, f"{value:.2g}", ha="center", va="center", fontsize=8, color="white")
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
            edgecolors="#2f7d65",
            linewidths=2.3,
            label="minimum calcule",
            zorder=4,
        )
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_title(title)
        ax.set_xlabel("mK")
        ax.grid(True, ls=":", lw=0.45, color="#cfd8df")
        fig.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04, label=column)
    axes[0].set_ylabel("Sy")
    axes[-1].legend(loc="best", fontsize=9)
    fig.suptitle("Fonction objectif en fonction des parametres")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _truth_parameters(truth_dir: Path | None) -> tuple[float, float] | None:
    if truth_dir is None:
        return None
    metadata = _read_json(truth_dir / "metadata.json")
    mk = _float(metadata.get("mK_true"))
    sy = _float(metadata.get("Sy_true"))
    if np.isfinite(mk) and np.isfinite(sy):
        return mk, sy
    return None


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


def _save_outflow_map_grid(truth_dir: Path | None, labels: tuple[str, ...], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    from hydromodpy.display._ugrid import render_face_field

    map_data = []
    positive_values = []
    for label in labels:
        root = RUN_ROOTS.get(label)
        if root is None or not root.is_dir():
            continue
        catalog, run = _open_first_run(root)
        try:
            drain = np.asarray(run.field("outflow_drain", timestep=-1), dtype=float).reshape(-1)
            log_values = np.full(drain.shape, np.nan, dtype=float)
            active = np.isfinite(drain) & (drain > 0.0)
            log_values[active] = np.log10(drain[active])
            if np.any(active):
                positive_values.extend(log_values[active].tolist())
            centroids, _ = mesh_cell_geometry(run.mesh.vertices, run.mesh.face_node_connectivity)
            map_data.append((label, root, drain, log_values, centroids))
        finally:
            catalog.close()
    if not map_data:
        return

    finite = np.asarray([value for value in positive_values if np.isfinite(value)], dtype=float)
    if finite.size:
        vmin = float(np.nanpercentile(finite, 5))
        vmax = float(np.nanpercentile(finite, 95))
        if np.isclose(vmin, vmax):
            vmin -= 1.0
            vmax += 1.0
    else:
        vmin, vmax = -12.0, -6.0

    n = len(map_data)
    ncols = min(2, n)
    nrows = int(np.ceil(n / ncols))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(nrows, ncols, figsize=(7.2 * ncols, 6.2 * nrows), dpi=150)
    axes_arr = np.asarray(axes).reshape(-1)
    for ax, (label, root, drain, log_values, centroids) in zip(axes_arr, map_data, strict=False):
        catalog, run = _open_first_run(root)
        try:
            plot_values = np.where(np.isfinite(log_values), log_values, vmin - 0.25)
            render_face_field(
                ax,
                run,
                plot_values,
                cmap="magma",
                vmin=vmin - 0.25,
                vmax=vmax,
                cbar_label="log10(outflow_drain)",
            )
        finally:
            catalog.close()
        active = np.isfinite(drain) & (drain > 0.0)
        if np.any(active):
            ax.scatter(
                centroids[active, 0],
                centroids[active, 1],
                s=7,
                color="#1f2933",
                alpha=0.45,
                linewidths=0,
                label="cellule drainante",
            )
        ax.set_title(f"{label} - {int(active.sum())}/{active.size} cellules actives")
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.grid(True, ls=":", lw=0.35, color="#cfd8df")
        ax.legend(
            handles=[
                Line2D(
                    [0],
                    [0],
                    marker="o",
                    color="none",
                    markerfacecolor="#1f2933",
                    markersize=5,
                    label="drainage actif",
                )
            ],
            loc="best",
            frameon=True,
            fontsize=8,
        )
    for ax in axes_arr[n:]:
        ax.set_axis_off()
    fig.suptitle("Cartes maillées des zones de drainage/suintement")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _save_network_support_diagnostics(
    truth_dir: Path | None, score_rows: list[dict[str, str]], path: Path
) -> None:
    if truth_dir is None:
        return
    candidate = _first_non_truth_candidate(score_rows)
    if candidate is None:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.lines import Line2D

    from hydromodpy.calibration.network_metrics import (
        active_network_mask,
        nearest_distances_to_mask,
    )

    d_ref = np.load(truth_dir / "steady_network_drain_by_cell.npz")["outflow_drain"]
    geometry = np.load(truth_dir / "cell_geometry.npz")
    centroids = geometry["centroids"]
    normalization = _read_json(truth_dir / "normalization.json")
    threshold = float(normalization.get("tau_network", 0.0))
    d_tol = float(normalization.get("d_tol", 1.0))

    catalog_path = _score_catalog_path(candidate.get("steady_catalog", ""))
    if catalog_path is None or not catalog_path.is_dir():
        return
    catalog = SimulationCatalog(catalog_path)
    try:
        run = catalog[catalog.resolve(candidate.get("steady_ref", "run_0001"))]
        d_sim = np.asarray(run.field("outflow_drain", timestep=-1), dtype=float).reshape(-1)
        polygons = _mesh_polygons(run)
    finally:
        catalog.close()

    ref_mask = active_network_mask(d_ref, threshold=threshold)
    sim_mask = active_network_mask(d_sim, threshold=threshold)
    true_positive = ref_mask & sim_mask
    false_negative = ref_mask & ~sim_mask
    false_positive = ~ref_mask & sim_mask

    classes = np.zeros(ref_mask.size, dtype=int)
    classes[true_positive] = 1
    classes[false_negative] = 2
    classes[false_positive] = 3
    colors = np.asarray(["#eef2f5", "#2f7d65", "#b5413c", "#d08b2c"], dtype=object)
    facecolors = colors[classes]

    dist_to_ref = nearest_distances_to_mask(centroids, ref_mask)
    dist_to_sim = nearest_distances_to_mask(centroids, sim_mask) if np.any(sim_mask) else None
    fp_dist = dist_to_ref[false_positive] / d_tol if np.any(false_positive) else np.asarray([])
    fn_dist = (
        dist_to_sim[false_negative] / d_tol
        if dist_to_sim is not None and np.any(false_negative)
        else np.asarray([])
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 5.3), dpi=150)

    ax_map = axes[0]
    coll = PolyCollection(polygons, facecolors=facecolors, edgecolors="#d8dee6", linewidths=0.25)
    ax_map.add_collection(coll)
    ax_map.autoscale_view()
    ax_map.set_aspect("equal", adjustable="box")
    ax_map.set_title(f"Support reseau: reference vs {candidate.get('candidate_id', 'candidat')}")
    ax_map.set_xlabel("X")
    ax_map.set_ylabel("Y")
    ax_map.grid(True, ls=":", lw=0.35, color="#cfd8df")
    ax_map.legend(
        handles=[
            Line2D(
                [0],
                [0],
                marker="s",
                color="none",
                markerfacecolor="#2f7d65",
                markersize=8,
                label="commun",
            ),
            Line2D(
                [0],
                [0],
                marker="s",
                color="none",
                markerfacecolor="#b5413c",
                markersize=8,
                label="manque candidat",
            ),
            Line2D(
                [0],
                [0],
                marker="s",
                color="none",
                markerfacecolor="#d08b2c",
                markersize=8,
                label="exces candidat",
            ),
        ],
        loc="best",
        frameon=True,
        fontsize=8,
    )

    ax_hist = axes[1]
    bins = np.linspace(
        0.0,
        max(
            1.0,
            float(np.nanmax(fp_dist)) if fp_dist.size else 0.0,
            float(np.nanmax(fn_dist)) if fn_dist.size else 0.0,
        ),
        12,
    )
    if fp_dist.size:
        ax_hist.hist(fp_dist, bins=bins, alpha=0.72, color="#d08b2c", label="exces candidat")
    if fn_dist.size:
        ax_hist.hist(fn_dist, bins=bins, alpha=0.72, color="#b5413c", label="manque candidat")
    if not fp_dist.size and not fn_dist.size:
        ax_hist.text(
            0.5, 0.5, "supports identiques", ha="center", va="center", transform=ax_hist.transAxes
        )
    ax_hist.set_title("Distance des erreurs au reseau oppose")
    ax_hist.set_xlabel("Distance / d_tol")
    ax_hist.set_ylabel("Nombre de cellules")
    ax_hist.grid(True, ls=":", lw=0.45, color="#cfd8df")
    handles, _ = ax_hist.get_legend_handles_labels()
    if handles:
        ax_hist.legend(loc="best", fontsize=8)

    summary = (
        f"ref={int(ref_mask.sum())}, sim={int(sim_mask.sum())}, "
        f"commun={int(true_positive.sum())}, "
        f"manques={int(false_negative.sum())}, exces={int(false_positive.sum())}"
    )
    fig.suptitle(f"Diagnostic spatial du terme reseau ({summary})")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _first_non_truth_candidate(score_rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in score_rows:
        if row.get("candidate_id") != "truth_identity" and row.get("status") == "completed":
            return row
    return None


def _mesh_polygons(run: Run) -> list[np.ndarray]:
    vertices = np.asarray(run.mesh.vertices)
    faces = np.asarray(run.mesh.face_node_connectivity)
    polygons = []
    for row in faces:
        nodes = row[row >= 0] if row.dtype.kind in "iu" else row[~np.isnan(row)]
        polygons.append(vertices[nodes.astype(int)][:, :2])
    return polygons


def _q_total_release_series(
    *, score_rows: list[dict[str, str]], truth_q: list[float]
) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    if truth_q:
        series["reference synthetique"] = truth_q
    for row in score_rows:
        cid = row.get("candidate_id", "")
        if cid == "truth_identity":
            continue
        catalog_path = _score_catalog_path(row.get("transient_catalog", ""))
        if catalog_path is None or not catalog_path.is_dir():
            continue
        try:
            with SimulationCatalog(catalog_path) as catalog:
                ref = row.get("transient_ref") or "run_0001"
                run = catalog[ref]
                stack = np.vstack(
                    [
                        np.asarray(run.field("outflow_drain", timestep=t), dtype=float).reshape(-1)
                        for t in range(int(run.n_timesteps or 0))
                    ]
                )
                series[cid or catalog_path.name] = list(q_total_release_from_drain_by_cell(stack))
        except Exception:
            continue
    return series


def _score_catalog_path(raw: Any) -> Path | None:
    if raw in (None, ""):
        return None
    path = Path(str(raw))
    if path.is_absolute():
        return path
    candidate = (ROOT / path).resolve()
    if candidate.exists():
        return candidate
    return (Path.cwd() / path).resolve()


def _page(
    *,
    normalization: dict[str, Any],
    k_rows: list[dict[str, str]],
    score_rows: list[dict[str, str]],
    figures: dict[str, Path],
    truth_dir: Path | None,
    score_table: Path | None,
) -> str:
    truth_label = _truth_label(truth_dir)
    score_label = link_relative(WEB_ROOT, score_table) if score_table is not None else ""
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>B0 diagnostic MF6</title>
  <style>
    :root {{
      color-scheme: light;
      --fg: #1f2933;
      --muted: #5d6875;
      --line: #d7dde5;
      --soft: #f4f7fa;
      --blue: #2662a5;
      --green: #26826a;
      --red: #b5413c;
      --orange: #b66a1f;
    }}
    body {{
      margin: 0;
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--fg);
      background: #ffffff;
    }}
    header {{
      padding: 22px 28px 14px;
      border-bottom: 1px solid var(--line);
    }}
    main {{
      padding: 18px 28px 32px;
      display: grid;
      gap: 22px;
    }}
    h1, h2, h3 {{ margin: 0; line-height: 1.2; }}
    h1 {{ font-size: 24px; }}
    h2 {{ font-size: 18px; }}
    h3 {{ font-size: 14px; margin-bottom: 8px; }}
    p {{ margin: 6px 0 0; color: var(--muted); }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 7px 8px;
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: var(--soft); font-weight: 650; color: #2c3744; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      align-items: start;
    }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
      overflow-x: auto;
    }}
    .metric-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .metric {{
      border-left: 3px solid var(--blue);
      background: var(--soft);
      padding: 7px 9px;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ font-size: 15px; }}
    .maps {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .figure-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
      gap: 14px;
      align-items: start;
      margin-top: 12px;
    }}
    .figure-card {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fff;
    }}
    .figure-card img {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .caption {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 7px;
    }}
    .map-title {{ font-weight: 650; margin: 0 0 6px; }}
    .legend {{ display: flex; gap: 12px; color: var(--muted); font-size: 12px; margin-top: 8px; }}
    .swatch {{ width: 10px; height: 10px; display: inline-block; border-radius: 50%; margin-right: 4px; }}
    .note {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}
    .muted {{ color: var(--muted); }}
    svg {{ max-width: 100%; height: auto; }}
  </style>
</head>
<body>
  <header>
    <h1>B0 diagnostic MF6 reseau + debit</h1>
    <p>Premier tableau de bord issu des runs reels site_01. Les grandeurs de normalisation restent fixes a partir du permanent de reference: <code>{safe(truth_label)}</code>.</p>
  </header>
  <main>
    <section class="panel">
      <h2>Sources du diagnostic</h2>
      <p>Package verite: <code>{safe(str(truth_dir or ""))}</code></p>
      <p>Table de scores: <code>{safe(score_label)}</code></p>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Normalisation</h2>
        {_normalization_metrics(normalization)}
      </div>
      <div class="panel">
        <h2>Choix de K</h2>
        <p>Le multiplicateur neutre mK=1.0 produit une zone drainante reduite. Le balayage steady indique une reference plus informative autour de mK=0.60-0.65.</p>
        {_k_chart(k_rows)}
      </div>
    </section>
    <section class="panel">
      <h2>Contexte spatial et budget</h2>
      <p>Les figures ci-dessous reutilisent les composants de diagnostic existants du projet : carte d'identite bassin et bilan solveur. Elles ancrent le cas B0 avant de regarder les distances reseau et la chronique de debit.</p>
      <div class="figure-grid">
        {_figure_card(figures.get("watershed_id_card"), "Bassin et exutoire", "Carte d'identite issue de WatershedIdCardFigure sur le run steady mK=0.65.")}
        {_figure_card(figures.get("water_budget_mK_0p65"), "Budget steady mK=0.65", "Budget MODFLOW agrege par composant, reutilise depuis WaterBudget.")}
      </div>
    </section>
    <section class="panel">
      <h2>Balayage steady K</h2>
      {_figure_card(figures.get("k_sweep_network_extent"), "Extension du drainage actif selon K", "La reference proposee mK=0.65 garde un reseau actif ni trop reduit ni trop diffus.")}
      {_k_table(k_rows)}
    </section>
    <section class="panel">
      <h2>Cartes d'affleurement / drainage</h2>
      <p>Cartes maillées de <code>outflow_drain</code> en permanent. Les cellules sans drainage sont affichees au niveau bas de l'echelle ; les points sombres signalent les cellules strictement actives.</p>
      {_figure_card(figures.get("outflow_drain_maps"), "Support spatial de Q_total_release", "Vue comparable aux cartes de suintement/drainage des autres rapports, mais sur le maillage DISV MF6.")}
    </section>
    <section class="panel">
      <h2>Diagnostic spatial reference / candidat</h2>
      <p>Comparaison du support actif <code>outflow_drain &gt; tau_network</code> entre la reference du truth package et le premier candidat score. La carte distingue le support commun, les cellules manquees et les cellules en exces.</p>
      {_figure_card(figures.get("network_support_diagnostics"), "Erreurs de support reseau", "La distance est exprimee en multiples de <code>d_tol</code>, la normalisation fixee depuis le permanent reference.")}
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Scores candidats</h2>
        {_score_table(score_rows)}
      </div>
      <div class="panel">
        <h2>Chronique Q_total_release</h2>
        {_figure_card(figures.get("q_total_release_timeseries"), "Flux total de sortie", "Somme temporelle des flux <code>outflow_drain</code> sur tout le domaine.")}
        {_figure_card(figures.get("score_components"), "Decomposition du cout", "Comparaison directe des termes normalises reseau et debit.")}
      </div>
    </section>
  </main>
</body>
</html>
"""


def _truth_label(truth_dir: Path | None) -> str:
    if truth_dir is None:
        return "absent"
    metadata = _read_json(truth_dir / "metadata.json")
    mk = metadata.get("mK_true")
    sy = metadata.get("Sy_true")
    if mk is not None and sy is not None:
        return f"{truth_dir.name} (mK={mk}, Sy={sy})"
    return truth_dir.name


def _figure_card(path: Path | None, title: str, caption: str) -> str:
    if path is None or not path.is_file():
        return (
            f'<div class="figure-card"><h3>{safe(title)}</h3>'
            '<p class="muted">Figure non disponible pour cette relance.</p></div>'
        )
    href = safe(link_relative(WEB_ROOT, path))
    return (
        f'<figure class="figure-card"><h3>{safe(title)}</h3>'
        f'<a href="{href}"><img src="{href}" alt="{safe(title)}"></a>'
        f'<figcaption class="caption">{caption}</figcaption></figure>'
    )


def _normalization_metrics(normalization: dict[str, Any]) -> str:
    items = [
        ("Q_ref_steady", "m3/s"),
        ("Qbar_ref", "m3/s"),
        ("L_ref", "m"),
        ("d_tol", "m"),
        ("alpha_Q", ""),
        ("w_reseau", ""),
        ("w_debit", ""),
    ]
    cells = []
    for key, unit in items:
        suffix = f" {unit}" if unit else ""
        cells.append(
            f'<div class="metric"><span>{html.escape(key)}</span>'
            f"<strong>{html.escape(_fmt(normalization.get(key), 5))}{suffix}</strong></div>"
        )
    return f'<div class="metric-row">{"".join(cells)}</div>'


def _k_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<p class="note">Aucune sortie de balayage K disponible.</p>'
    rows_sorted = sorted(rows, key=lambda row: _float(row.get("mK")))
    body = []
    for row in rows_sorted:
        body.append(
            "<tr>"
            f"<td>{html.escape(row.get('label', ''))}</td>"
            f"<td>{_fmt(row.get('mK'), 2)}</td>"
            f"<td>{html.escape(str(row.get('n_active', '')))}</td>"
            f"<td>{_fmt(100.0 * _float(row.get('active_fraction')), 2)}%</td>"
            f"<td>{_fmt(row.get('equivalent_length_m'), 1)}</td>"
            f"<td>{_fmt(row.get('q_total_m3_s'), 6)}</td>"
            f"<td>{_fmt(row.get('q_max_m3_s'), 6)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>run</th><th>mK</th><th>cellules actives</th>"
        "<th>fraction</th><th>L equiv. m</th><th>Q total m3/s</th><th>q max m3/s</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


def _k_chart(rows: list[dict[str, str]]) -> str:
    data = [
        (_float(row.get("mK")), _float(row.get("equivalent_length_m")))
        for row in rows
        if np.isfinite(_float(row.get("mK")))
        and np.isfinite(_float(row.get("equivalent_length_m")))
    ]
    if len(data) < 2:
        return '<p class="note">Pas assez de points pour tracer la tendance.</p>'
    data.sort()
    width, height = 360, 190
    pad_l, pad_b, pad_t, pad_r = 42, 28, 14, 12
    xs = np.asarray([p[0] for p in data], dtype=float)
    ys = np.asarray([p[1] for p in data], dtype=float)
    xmin, xmax = float(xs.min()), float(xs.max())
    ymin, ymax = 0.0, float(ys.max() * 1.08)

    def sx(x: float) -> float:
        return pad_l + (x - xmin) / (xmax - xmin) * (width - pad_l - pad_r)

    def sy(y: float) -> float:
        return height - pad_b - (y - ymin) / (ymax - ymin) * (height - pad_t - pad_b)

    points = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in data)
    circles = "".join(
        f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" fill="#2662a5" />'
        f'<text x="{sx(x):.1f}" y="{sy(y) - 8:.1f}" text-anchor="middle" font-size="10">{x:.2f}</text>'
        for x, y in data
    )
    return f"""
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="Longueur de reseau selon mK">
        <line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" y2="{height - pad_b}" stroke="#8a96a3" />
        <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height - pad_b}" stroke="#8a96a3" />
        <polyline points="{points}" fill="none" stroke="#2662a5" stroke-width="2.5" />
        {circles}
        <text x="{width / 2:.1f}" y="{height - 5}" text-anchor="middle" font-size="11" fill="#5d6875">mK</text>
        <text x="12" y="{height / 2:.1f}" text-anchor="middle" transform="rotate(-90 12 {height / 2:.1f})" font-size="11" fill="#5d6875">L equiv. m</text>
      </svg>
    """


def _score_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<p class="note">Aucun score candidat disponible.</p>'
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(row.get('candidate_id', ''))}</td>"
            f"<td>{_fmt(row.get('mK'), 2)}</td>"
            f"<td>{_fmt(row.get('Sy'), 3)}</td>"
            f"<td>{_fmt(row.get('J'), 4)}</td>"
            f"<td>{_fmt(row.get('C_reseau_phys'), 4)}</td>"
            f"<td>{_fmt(row.get('C_debit_phys'), 4)}</td>"
            f"<td>{_fmt(row.get('network.n_sim_active'), 0)}</td>"
            f"<td>{_fmt(row.get('discharge.RMSE_Q_over_Qbar_ref'), 4)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>candidat</th><th>mK</th><th>Sy</th><th>J</th>"
        "<th>C reseau</th><th>C debit</th><th>n actif</th><th>RMSE/Qbar</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


def _map_panel(label: str) -> str:
    root = RUN_ROOTS.get(label)
    if root is None or not root.is_dir():
        return f'<div><p class="map-title">{html.escape(label)}</p><p class="note">run absent</p></div>'
    try:
        with SimulationCatalog(root) as catalog:
            sims = catalog.simulations
            run = Run.from_id(catalog, str(sims.iloc[0]["sim_id"]))
            drain = np.asarray(run.field("outflow_drain", timestep=-1), dtype=float).reshape(-1)
            mesh = run.mesh
            centroids, _ = mesh_cell_geometry(mesh.vertices, mesh.face_node_connectivity)
    except Exception as exc:  # pragma: no cover - diagnostic best effort
        return (
            f'<div><p class="map-title">{html.escape(label)}</p>'
            f'<p class="note">{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</p></div>'
        )
    active = drain > 0.0
    svg = _centroid_map(centroids, drain)
    return (
        f'<div><p class="map-title">{html.escape(label)} '
        f'<span class="note">({int(active.sum())}/{active.size})</span></p>{svg}</div>'
    )


def _centroid_map(centroids: np.ndarray, drain: np.ndarray) -> str:
    width, height = 280, 220
    pad = 10.0
    x = centroids[:, 0]
    y = centroids[:, 1]
    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = float(y.min()), float(y.max())
    scale = min(
        (width - 2 * pad) / max(xmax - xmin, 1.0), (height - 2 * pad) / max(ymax - ymin, 1.0)
    )
    used_w = (xmax - xmin) * scale
    used_h = (ymax - ymin) * scale
    ox = (width - used_w) / 2.0
    oy = (height - used_h) / 2.0

    def sx(val: float) -> float:
        return ox + (val - xmin) * scale

    def sy(val: float) -> float:
        return height - oy - (val - ymin) * scale

    base = []
    active = []
    qmax = float(np.max(drain)) if drain.size else 0.0
    for xi, yi, qi in zip(x, y, drain, strict=False):
        if qi > 0.0:
            radius = 2.6 + 4.4 * (float(qi) / qmax if qmax > 0.0 else 0.0)
            active.append(
                f'<circle cx="{sx(float(xi)):.1f}" cy="{sy(float(yi)):.1f}" r="{radius:.2f}" fill="#b5413c" fill-opacity="0.76" />'
            )
        else:
            base.append(
                f'<circle cx="{sx(float(xi)):.1f}" cy="{sy(float(yi)):.1f}" r="1.15" fill="#c8d0d9" fill-opacity="0.72" />'
            )
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(base)}{"".join(active)}</svg>'


def _hydrograph(score_rows: list[dict[str, str]], truth_q: list[float]) -> str:
    series = {"truth": truth_q}
    for row in score_rows:
        cid = row.get("candidate_id", "")
        if cid == "truth_identity":
            continue
        catalog_path = Path(row.get("transient_catalog", ""))
        if not catalog_path.is_absolute():
            catalog_path = (
                ROOT / catalog_path.relative_to(ROOT)
                if str(catalog_path).startswith(str(ROOT))
                else Path.cwd() / catalog_path
            )
        if not catalog_path.is_dir():
            continue
        try:
            with SimulationCatalog(catalog_path) as catalog:
                ref = row.get("transient_ref") or "run_0001"
                run = catalog[ref]
                stack = np.vstack(
                    [
                        np.asarray(run.field("outflow_drain", timestep=t), dtype=float).reshape(-1)
                        for t in range(int(run.n_timesteps or 0))
                    ]
                )
                series[cid] = list(q_total_release_from_drain_by_cell(stack))
        except Exception:
            continue
    if not truth_q:
        return '<p class="note">Aucune chronique de reference disponible.</p>'
    return _line_chart(series)


def _line_chart(series: dict[str, list[float]]) -> str:
    width, height = 520, 240
    pad_l, pad_b, pad_t, pad_r = 44, 30, 14, 14
    values = [v for vals in series.values() for v in vals if np.isfinite(v)]
    if not values:
        return '<p class="note">Aucune valeur finie.</p>'
    n = max(len(vals) for vals in series.values())
    ymin, ymax = 0.0, float(max(values) * 1.08)

    def sx(i: int) -> float:
        return pad_l + i / max(n - 1, 1) * (width - pad_l - pad_r)

    def sy(v: float) -> float:
        return height - pad_b - (v - ymin) / (ymax - ymin) * (height - pad_t - pad_b)

    colors = ["#2662a5", "#b5413c", "#26826a", "#b66a1f"]
    lines = []
    legend = []
    for idx, (name, vals) in enumerate(series.items()):
        color = colors[idx % len(colors)]
        points = " ".join(f"{sx(i):.1f},{sy(float(v)):.1f}" for i, v in enumerate(vals))
        lines.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.2" />'
        )
        legend.append(
            f'<span><i class="swatch" style="background:{color}"></i>{html.escape(name)}</span>'
        )
    return f"""
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="Hydrogramme">
        <line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" y2="{height - pad_b}" stroke="#8a96a3" />
        <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height - pad_b}" stroke="#8a96a3" />
        {"".join(lines)}
        <text x="{width / 2:.1f}" y="{height - 6}" text-anchor="middle" font-size="11" fill="#5d6875">periode mensuelle</text>
        <text x="12" y="{height / 2:.1f}" text-anchor="middle" transform="rotate(-90 12 {height / 2:.1f})" font-size="11" fill="#5d6875">Q m3/s</text>
      </svg>
      <div class="legend">{"".join(legend)}</div>
    """


if __name__ == "__main__":
    main()
