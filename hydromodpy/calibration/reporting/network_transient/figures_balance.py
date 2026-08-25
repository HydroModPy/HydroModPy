"""Steady water-balance, recharge chronicle and Q-timeseries figures."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.calibration.observations.network_transient_truth import (
    q_total_release_from_drain_by_cell,
)
from hydromodpy.calibration.reporting.network_transient import io as _nt_io
from hydromodpy.calibration.reporting.network_transient import state as _state
from hydromodpy.calibration.reporting.network_transient.figures_objective import (
    _best_completed_candidate_id,
)
from hydromodpy.calibration.reporting.network_transient.geometry import (
    _score_catalog_path,
    _score_file_path,
)
from hydromodpy.results.catalog import Catalog

_read_csv = _nt_io.read_csv
_read_json = _nt_io.read_json
_read_toml = _nt_io.read_toml
_float = _nt_io.coerce_float


def _save_steady_balance_didactic(
    truth_dir: Path | None, rows: list[dict[str, str]], path: Path
) -> None:
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
        q_error_pct = 100.0 * (q / q_ref - 1.0)
        ax.plot(
            x,
            q_error_pct,
            marker="o",
            color="#17202a",
            lw=1.6,
            label="ecart Q_total",
        )
        ax2 = ax.twinx()
        ax2.plot(x, active, marker="s", color="#b5413c", lw=1.6, label="cellules actives")
        ax.axhline(0.0, color="#7a8694", ls=":", lw=1.0)
        ax.axvline(0.65, color="#2662a5", ls="--", lw=1.1, label="mK cible")
        ax.set_xlabel("mK")
        ax.set_ylabel("Ecart Q_total (%)")
        ax2.set_ylabel("Cellules actives (%)")
        ax.set_title("Flux total peu discriminant")
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
    cfg = _read_toml(_state.report_facade().SOURCE_TRANSIENT_CONFIG)
    data = cfg.get("data", {}) if isinstance(cfg.get("data"), dict) else {}
    recharge = data.get("recharge", {}) if isinstance(data.get("recharge"), dict) else {}
    sources = recharge.get("sources", [])
    if not sources:
        return np.asarray([], dtype=float)
    values = sources[0].get("values", []) if isinstance(sources[0], dict) else []
    return np.asarray(values, dtype=float).reshape(-1)


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
    best_name = _best_completed_candidate_id(score_rows)
    for name, values in series.items():
        if name in ("reference synthetique", best_name):
            continue
        arr = np.asarray(values, dtype=float)
        if arr.size:
            ax.plot(np.arange(arr.size), arr, lw=1.0, color="#9aa4af", alpha=0.34, zorder=1)
    if best_name and best_name in series:
        arr = np.asarray(series[best_name], dtype=float)
        ax.plot(
            np.arange(arr.size),
            arr,
            lw=2.0,
            color="#c43b2f",
            alpha=0.95,
            zorder=3,
            label=f"optimum calcule: {best_name}",
        )
    if "reference synthetique" in series:
        arr = np.asarray(series["reference synthetique"], dtype=float)
        ax.plot(
            np.arange(arr.size),
            arr,
            marker="o",
            ms=3.2,
            lw=2.5,
            color="#17202a",
            zorder=4,
            label="reference synthetique",
        )
    ax.set_title("Chronique mensuelle Q_total_release")
    ax.set_xlabel("Periode mensuelle")
    ax.set_ylabel("Q_total_release (m3/s)")
    ax.grid(True, ls=":", lw=0.45, color="#cfd8df")
    ax.legend(loc="best", fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _q_total_release_series(
    *, score_rows: list[dict[str, str]], truth_q: list[float]
) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    if truth_q:
        series["reference synthetique"] = truth_q
    for row in score_rows:
        cid = row.get("candidate_id", "")
        q_path = _score_file_path(row.get("transient_q_csv", ""))
        if q_path is not None and q_path.is_file():
            try:
                q_rows = _read_csv(q_path)
                series[cid or q_path.stem] = [
                    _float(item.get("q_total_release")) for item in q_rows
                ]
                continue
            except Exception:
                pass
        catalog_path = _score_catalog_path(row.get("transient_catalog", ""))
        if catalog_path is None or not catalog_path.is_dir():
            continue
        try:
            with Catalog(catalog_path) as catalog:
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
