from __future__ import annotations

import json
from argparse import Namespace
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hydromodpy.calibration.reporting.network_transient import args as _nt_args
from hydromodpy.calibration.reporting.network_transient import blocks as _blocks
from hydromodpy.calibration.reporting.network_transient import io as _nt_io
from hydromodpy.calibration.reporting.network_transient import state as _state
from hydromodpy.calibration.reporting.network_transient.figures_balance import (
    _q_total_release_series,
    _recharge_values_from_config,
    _save_q_timeseries_figure,
    _save_recharge_chronicle_figure,
    _save_steady_balance_didactic,
)
from hydromodpy.calibration.reporting.network_transient.figures_objective import (
    _axis_bounds,
    _best_completed_candidate_id,
    _log_objective_values,
    _nearest_value,
    _objective_grid_image,
    _plot_objective_cut,
    _save_objective_parameter_maps,
    _save_objective_profile_cuts,
    _truth_parameters,
)
from hydromodpy.calibration.reporting.network_transient.figures_outflow import (
    _network_map_source_label,
    _outflow_drain_from_npz,
    _save_dem_context_map,
    _save_outflow_map_grid,
    _steady_drain_from_score_row,
)
from hydromodpy.calibration.reporting.network_transient.figures_watershed import (
    _as_int_str,
    _draw_watershed_metadata,
    _draw_watershed_topography,
    _extent_from_transform,
    _load_run_dem,
    _mark_watershed_outlet,
    _open_first_run,
    _plot_watershed_id_card,
    _plot_watershed_id_card_placeholder,
    _save_watershed_id_card,
)

# Re-export the moved private helpers so the facade surface
# (network_transient_html.<name>) and its monkeypatch points stay stable.
from hydromodpy.calibration.reporting.network_transient.geometry import (
    _candidate_is_truth,
    _cell_node_id_values,
    _drain_facecolors,
    _first_non_truth_candidate,
    _iter_geometry_line_coords,
    _mesh_context_from_cell_geometry,
    _mesh_context_from_truth_package,
    _mesh_polygons,
    _origin_from_config_or_centroids,
    _plot_geographic_lines,
    _plot_topography,
    _polygon_bounds,
    _relative_gdf_bounds,
    _relative_origin,
    _relative_polygons,
    _safe_geographic,
    _score_catalog_path,
    _score_file_path,
    _topography_context,
    _watershed_clip_patch,
)
from hydromodpy.calibration.reporting.network_transient.manifest import (
    _manifest_contract,
    _manifest_normalization,
    _manifest_score_row,
    _reference_manifest_payload,
    _sha256_file,
    _write_reference_manifest,
)

REPO_ROOT = _state.REPO_ROOT
DEFAULT_EXAMPLE_ROOT = _state.DEFAULT_EXAMPLE_ROOT
ROOT = _state.ROOT
SOURCE_TRANSIENT_CONFIG = _state.SOURCE_TRANSIENT_CONFIG
REAL_ROOT = _state.REAL_ROOT
WEB_ROOT = _state.WEB_ROOT
FIGURE_ROOT = _state.FIGURE_ROOT
PAGE_TITLE = _state.PAGE_TITLE
TRUTH_PACKAGE_CANDIDATES = _state.TRUTH_PACKAGE_CANDIDATES
SCORE_TABLE_CANDIDATES = _state.SCORE_TABLE_CANDIDATES
PATH_BASE = _state.PATH_BASE
REFERENCE_RUN_ROOT = _state.REFERENCE_RUN_ROOT
STEADY_SUMMARY_CSV = _state.STEADY_SUMMARY_CSV


NetworkTransientHtmlArtifactReport = _nt_io.NetworkTransientHtmlArtifactReport

__all__ = [
    "NetworkTransientHtmlArtifactReport",
    "build_network_transient_html",
    "build_network_transient_html_from_args",
    "inspect_network_transient_html_artifacts",
    "main",
    "_as_int_str",
    "_axis_bounds",
    "_best_completed_candidate_id",
    "_candidate_is_truth",
    "_cell_node_id_values",
    "_drain_facecolors",
    "_draw_watershed_metadata",
    "_draw_watershed_topography",
    "_extent_from_transform",
    "_first_non_truth_candidate",
    "_iter_geometry_line_coords",
    "_load_run_dem",
    "_log_objective_values",
    "_manifest_contract",
    "_manifest_normalization",
    "_manifest_score_row",
    "_mark_watershed_outlet",
    "_mesh_context_from_cell_geometry",
    "_mesh_context_from_truth_package",
    "_mesh_polygons",
    "_nearest_value",
    "_network_map_source_label",
    "_objective_grid_image",
    "_open_first_run",
    "_origin_from_config_or_centroids",
    "_outflow_drain_from_npz",
    "_plot_geographic_lines",
    "_plot_objective_cut",
    "_plot_topography",
    "_plot_watershed_id_card",
    "_plot_watershed_id_card_placeholder",
    "_polygon_bounds",
    "_q_total_release_series",
    "_recharge_values_from_config",
    "_reference_manifest_payload",
    "_relative_gdf_bounds",
    "_relative_origin",
    "_relative_polygons",
    "_safe_geographic",
    "_save_dem_context_map",
    "_save_objective_parameter_maps",
    "_save_objective_profile_cuts",
    "_save_outflow_map_grid",
    "_save_q_timeseries_figure",
    "_save_recharge_chronicle_figure",
    "_save_steady_balance_didactic",
    "_save_watershed_id_card",
    "_score_catalog_path",
    "_score_file_path",
    "_sha256_file",
    "_steady_drain_from_score_row",
    "_topography_context",
    "_truth_parameters",
    "_watershed_clip_patch",
    "_write_reference_manifest",
]


def main() -> None:
    out = build_network_transient_html_from_args(_parse_args())
    print(out)


def build_network_transient_html(
    *,
    real_root: Path = REAL_ROOT,
    web_root: Path | None = None,
    source_transient_config: Path = SOURCE_TRANSIENT_CONFIG,
    path_base: Path | None = None,
    page_title: str = PAGE_TITLE,
    reference_run_root: Path | None = None,
    steady_summary_csv: Path | None = None,
    truth_packages: Iterable[Path] | None = None,
    score_tables: Iterable[Path] | None = None,
) -> Path:
    """Build the calibration diagnostic page from Python code."""

    args = Namespace(
        real_root=real_root,
        web_root=web_root,
        source_transient_config=source_transient_config,
        path_base=path_base,
        page_title=page_title,
        reference_run_root=reference_run_root,
        steady_summary_csv=steady_summary_csv,
        truth_package=list(truth_packages) if truth_packages is not None else None,
        score_table=list(score_tables) if score_tables is not None else None,
    )
    return build_network_transient_html_from_args(args)


def build_network_transient_html_from_args(args: Namespace) -> Path:
    """Build the calibration diagnostic page from parsed CLI arguments."""

    _configure_from_args(args)
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    artifact_report = inspect_network_transient_html_artifacts(
        real_root=REAL_ROOT,
        source_transient_config=SOURCE_TRANSIENT_CONFIG,
        reference_run_root=REFERENCE_RUN_ROOT,
        steady_summary_csv=STEADY_SUMMARY_CSV,
        truth_packages=TRUTH_PACKAGE_CANDIDATES,
        score_tables=SCORE_TABLE_CANDIDATES,
    )
    truth_dir = artifact_report.truth_dir
    score_table = artifact_report.score_table
    k_rows = _read_csv(STEADY_SUMMARY_CSV)
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
    _prune_stale_figures(figures)

    html_text = _page(
        normalization=normalization,
        score_rows=score_rows,
        figures=figures,
        truth_dir=truth_dir,
        score_table=score_table,
        artifact_report=artifact_report,
    )
    out = WEB_ROOT / "index.html"
    (WEB_ROOT / "network_transient_html_artifacts.json").write_text(
        json.dumps(artifact_report.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    out.write_text(html_text, encoding="utf-8")
    _write_reference_manifest(
        out,
        artifact_report=artifact_report,
        normalization=normalization,
        score_rows=score_rows,
    )
    return out


def _parse_args() -> Namespace:
    return _nt_args.parse_args(
        real_root=REAL_ROOT,
        source_transient_config=SOURCE_TRANSIENT_CONFIG,
        page_title=PAGE_TITLE,
    )


def _configure_from_args(args: Namespace) -> None:
    global FIGURE_ROOT
    global PAGE_TITLE
    global PATH_BASE
    global REAL_ROOT
    global REFERENCE_RUN_ROOT
    global SCORE_TABLE_CANDIDATES
    global SOURCE_TRANSIENT_CONFIG
    global STEADY_SUMMARY_CSV
    global TRUTH_PACKAGE_CANDIDATES
    global WEB_ROOT

    REAL_ROOT = args.real_root.resolve()
    WEB_ROOT = (args.web_root if args.web_root is not None else REAL_ROOT / "web").resolve()
    FIGURE_ROOT = WEB_ROOT / "figures"
    PAGE_TITLE = args.page_title
    SOURCE_TRANSIENT_CONFIG = args.source_transient_config.resolve()
    PATH_BASE = (
        args.path_base.resolve()
        if args.path_base is not None
        else _nt_io.default_path_base(REAL_ROOT)
    )
    REFERENCE_RUN_ROOT = (
        args.reference_run_root.resolve()
        if args.reference_run_root is not None
        else REAL_ROOT / "candidate_mK_0p65_Sy_0p05_steady_mf6"
    )
    STEADY_SUMMARY_CSV = (
        args.steady_summary_csv.resolve()
        if args.steady_summary_csv is not None
        else REAL_ROOT / "steady_mK_network_extent_summary.csv"
    )
    TRUTH_PACKAGE_CANDIDATES = tuple(
        path.resolve() for path in (args.truth_package or _nt_io.default_truth_packages(REAL_ROOT))
    )
    SCORE_TABLE_CANDIDATES = tuple(
        path.resolve() for path in (args.score_table or _nt_io.default_score_tables(REAL_ROOT))
    )


def inspect_network_transient_html_artifacts(
    *,
    real_root: Path = REAL_ROOT,
    source_transient_config: Path = SOURCE_TRANSIENT_CONFIG,
    reference_run_root: Path | None = None,
    steady_summary_csv: Path | None = None,
    truth_packages: Iterable[Path] | None = None,
    score_tables: Iterable[Path] | None = None,
) -> NetworkTransientHtmlArtifactReport:
    """Inspect whether the standard network/transient HTML artifacts are present."""
    return _nt_io.inspect_network_transient_html_artifacts(
        real_root=real_root,
        source_transient_config=source_transient_config,
        reference_run_root=reference_run_root,
        steady_summary_csv=steady_summary_csv,
        truth_packages=truth_packages,
        score_tables=score_tables,
    )


_read_csv = _nt_io.read_csv
_read_json = _nt_io.read_json
_read_truth_discharge = _nt_io.read_truth_discharge
_float = _nt_io.coerce_float


def _generate_figures(
    *,
    truth_dir: Path | None,
    k_rows: list[dict[str, str]],
    score_rows: list[dict[str, str]],
    truth_q: list[float],
) -> dict[str, Path]:
    figures: dict[str, Path] = {}
    figure_specs = (
        ("watershed_id_card", _save_watershed_id_card, (REFERENCE_RUN_ROOT,)),
        ("dem_context_map", _save_dem_context_map, (truth_dir, REFERENCE_RUN_ROOT)),
        ("steady_balance_didactic", _save_steady_balance_didactic, (truth_dir, k_rows)),
        ("recharge_chronicle", _save_recharge_chronicle_figure, ()),
        ("outflow_drain_maps", _save_outflow_map_grid, (truth_dir, score_rows)),
        ("q_total_release_timeseries", _save_q_timeseries_figure, (score_rows, truth_q)),
        ("objective_parameter_maps", _save_objective_parameter_maps, (truth_dir, score_rows)),
        ("objective_profile_cuts", _save_objective_profile_cuts, (truth_dir, score_rows)),
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


def _prune_stale_figures(figures: dict[str, Path]) -> None:
    expected = {path.resolve() for path in figures.values()}
    for path in FIGURE_ROOT.glob("*.png"):
        if path.resolve() not in expected:
            path.unlink()


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

    path.parent.mkdir(parents=True, exist_ok=True)
    catalog: SimulationCatalog | None = None
    fig = None
    try:
        try:
            catalog, run = _open_first_run(root)
        except Exception:
            fig = _plot_watershed_id_card_placeholder(root)
        else:
            fig = _plot_watershed_id_card(run)
        fig.savefig(path, dpi=150, bbox_inches="tight")
    finally:
        if fig is not None:
            plt.close(fig)
        if catalog is not None:
            catalog.close()


def _plot_watershed_id_card(run: Run):
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    fig = plt.figure(figsize=(11.5, 7.5), dpi=150, constrained_layout=True)
    gs = GridSpec(1, 2, figure=fig, width_ratios=[3.0, 1.3])
    ax_topo = fig.add_subplot(gs[0, 0])
    ax_meta = fig.add_subplot(gs[0, 1])

    _draw_watershed_topography(ax_topo, run)
    _draw_watershed_metadata(ax_meta, run)
    fig.suptitle(
        f"Watershed ID card - {run.name or str(run.sim_id)[:8]}",
        fontweight="bold",
        fontsize=14,
    )
    return fig


def _plot_watershed_id_card_placeholder(root: Path):
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    fig = plt.figure(figsize=(11.5, 7.5), dpi=150, constrained_layout=True)
    gs = GridSpec(1, 2, figure=fig, width_ratios=[3.0, 1.3])
    ax_topo = fig.add_subplot(gs[0, 0])
    ax_meta = fig.add_subplot(gs[0, 1])

    ax_topo.set_axis_off()
    ax_topo.text(
        0.5,
        0.5,
        "reference run unavailable",
        ha="center",
        va="center",
        transform=ax_topo.transAxes,
        fontsize=10,
        color="gray",
    )
    ax_topo.set_title("Topography")

    ax_meta.set_axis_off()
    rows = [
        ("Reference", root.name or "-"),
        ("Status", "unavailable"),
    ]
    table = ax_meta.table(
        cellText=[[key, value] for key, value in rows],
        loc="center",
        colWidths=[0.45, 0.55],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.4)
    for (_row_idx, col_idx), cell in table.get_celld().items():
        if col_idx == 0:
            cell.set_facecolor("#f2f2f2")
            cell.set_text_props(fontweight="bold")
        cell.set_edgecolor("#c8c8c8")
    ax_meta.set_title("Identity")
    fig.suptitle("Watershed ID card", fontweight="bold", fontsize=14)
    return fig


def _draw_watershed_topography(ax: Any, run: Run) -> None:
    dem, raster = _load_run_dem(run)
    if dem is None:
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "no DEM ingested for this run",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=10,
            color="gray",
        )
        ax.set_title("Topography")
        return

    extent = _extent_from_transform(raster, dem.shape) if raster is not None else None
    nodata = getattr(raster, "nodata", None)
    dem_plot = dem.astype(float)
    if nodata is not None:
        dem_plot = np.where(np.isclose(dem_plot, float(nodata)), np.nan, dem_plot)
    dem_plot = np.where(dem_plot < -1e30, np.nan, dem_plot)

    im = ax.imshow(
        dem_plot,
        cmap="terrain",
        origin="upper",
        extent=extent,
        interpolation="nearest",
    )
    ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Elevation (m)")
    _mark_watershed_outlet(ax, run)
    ax.set_title("Topography")
    ax.set_aspect("equal")
    ax.grid(True, color="#d7dee5", linewidth=0.4, alpha=0.55)
    ax.set_xlabel("x")
    ax.set_ylabel("y")


def _load_run_dem(run: Run) -> tuple[np.ndarray | None, Any | None]:
    for name in ("watershed_dem", "dem", "watershed_fill"):
        try:
            raster = run.geographic_raster(name)
        except Exception:
            continue
        data = getattr(raster, "data", None)
        if data is None:
            continue
        arr = np.asarray(data)
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.size:
            return arr, raster
    return None, None


def _mark_watershed_outlet(ax: Any, run: Run) -> None:
    try:
        meta = run._catalog.read_geographic_metadata(run.sim_id)
    except Exception:
        return
    if not isinstance(meta, dict):
        return
    x_out = _float(meta.get("x_outlet"))
    y_out = _float(meta.get("y_outlet"))
    if not np.isfinite(x_out) or not np.isfinite(y_out):
        return
    ax.plot(
        x_out,
        y_out,
        marker="*",
        markersize=12,
        color="red",
        markeredgecolor="black",
        linestyle="None",
        label="outlet",
        zorder=10,
    )
    ax.legend(loc="best")


def _draw_watershed_metadata(ax: Any, run: Run) -> None:
    ax.set_axis_off()
    sid = str(run.sim_id or "")
    sid_short = f"{sid[:8]}..." if len(sid) > 10 else sid
    rows = [
        ("ID", sid_short),
        ("Name", str(run.name or "-")),
        ("Project", str(run.project or "-")),
        ("Solver", str(run.solver or "-")),
        ("Regime", str(run.flow_regime or "-")),
        ("Status", str(run.status or "-")),
        ("Cells", _as_int_str(run.n_cells)),
        ("Layers", _as_int_str(run.n_layers)),
        ("Timesteps", _as_int_str(run.n_timesteps)),
    ]
    table = ax.table(
        cellText=[[key, value] for key, value in rows],
        loc="center",
        colWidths=[0.45, 0.55],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.4)
    for (_row_idx, col_idx), cell in table.get_celld().items():
        if col_idx == 0:
            cell.set_facecolor("#f2f2f2")
            cell.set_text_props(fontweight="bold")
        cell.set_edgecolor("#c8c8c8")
    ax.set_title("Identity")


def _extent_from_transform(raster: Any, shape: tuple[int, ...]) -> list[float] | None:
    transform = getattr(raster, "transform", None)
    if not transform or len(transform) < 6 or len(shape) < 2:
        return None
    a, _b, c, _d, e, f = (float(value) for value in transform[:6])
    rows, cols = shape[-2:]
    xmin = c
    xmax = c + a * cols
    ymax = f
    ymin = f + e * rows
    return [xmin, xmax, ymin, ymax]


def _as_int_str(value: Any) -> str:
    if value in (None, 0):
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


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
    cfg = _read_toml(SOURCE_TRANSIENT_CONFIG)
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


def _reference_run_geometry_context(
    *,
    fallback_origin: Any,
    fallback_polygons: Any,
    fallback_cell_topography: Any,
) -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    """Load geometry/geography from the reference run.

    Falls back to the truth-package context (mesh + topography) when the
    reference run is unavailable or its geometry cannot be resolved.
    Returns ``(origin, polygons, cell_topography, topo, watershed,
    watershed_contour, river_network)``.
    """
    origin = fallback_origin
    polygons = fallback_polygons
    cell_topography = fallback_cell_topography
    topo = None
    watershed = None
    watershed_contour = None
    river_network = None

    if REFERENCE_RUN_ROOT.is_dir():
        try:
            catalog, run = _open_first_run(REFERENCE_RUN_ROOT)
        except Exception:
            catalog = None
        if catalog is not None:
            try:
                try:
                    centroids, _ = mesh_cell_geometry(
                        run.mesh.vertices, run.mesh.face_node_connectivity
                    )
                    origin = _relative_origin(run, centroids)
                    polygons = _relative_polygons(_mesh_polygons(run), origin)
                    cell_topography = None
                except Exception:
                    pass
                if origin is not None:
                    topo = _topography_context(run, origin)
                    watershed = _safe_geographic(run, "watershed")
                    watershed_contour = _safe_geographic(run, "watershed_contour")
                    river_network = _safe_geographic(run, "hydrographic_network_generated")
            finally:
                catalog.close()

    return origin, polygons, cell_topography, topo, watershed, watershed_contour, river_network


def _save_outflow_map_grid(
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
    from matplotlib.cm import ScalarMappable
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import LogNorm, Normalize

    from hydromodpy.calibration.metrics.network import active_network_mask

    d_ref = np.load(truth_dir / "steady_network_drain_by_cell.npz")["outflow_drain"]
    normalization = _read_json(truth_dir / "normalization.json")
    threshold = float(normalization.get("tau_network", 0.0))

    fallback_context = _mesh_context_from_truth_package(truth_dir)
    origin, polygons, cell_topography, topo, watershed, watershed_contour, river_network = (
        _reference_run_geometry_context(
            fallback_origin=None if fallback_context is None else fallback_context["origin"],
            fallback_polygons=None if fallback_context is None else fallback_context["polygons"],
            fallback_cell_topography=(
                None if fallback_context is None else fallback_context["cell_topography"]
            ),
        )
    )

    if origin is None or polygons is None or len(polygons) != d_ref.size:
        return

    d_sim = _steady_drain_from_score_row(candidate)
    if d_sim is None or d_sim.size != d_ref.size:
        return
    ref_mask = active_network_mask(d_ref, threshold=threshold)
    sim_mask = active_network_mask(d_sim, threshold=threshold)
    true_positive = ref_mask & sim_mask
    false_negative = ref_mask & ~sim_mask
    false_positive = ~ref_mask & sim_mask

    positive_values = np.concatenate((d_ref[d_ref > threshold], d_sim[d_sim > threshold]))
    if positive_values.size:
        vmin = max(float(np.nanmin(positive_values)) * 0.5, 1.0e-12)
        vmax = float(np.nanmax(positive_values))
    else:
        vmin, vmax = 1.0e-12, 1.0
    norm = LogNorm(vmin=vmin, vmax=max(vmax, vmin * 10.0))
    cmap = plt.get_cmap("magma")

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 6.0), dpi=150, sharex=True, sharey=True)
    panels = (
        ("Objectif cible", d_ref, ref_mask),
        (
            f"Meilleur candidat: {candidate.get('candidate_id', 'candidat')}",
            d_sim,
            sim_mask,
        ),
    )
    mappable = None
    bounds = _relative_gdf_bounds(watershed, origin) if watershed is not None else None
    if bounds is None:
        bounds = _polygon_bounds(polygons)
    for ax, (title, drain, mask) in zip(axes, panels, strict=False):
        clip_patch = _watershed_clip_patch(watershed, origin, ax) if watershed is not None else None
        image = _plot_topography(ax, topo, clip_patch=clip_patch)
        del image
        if topo is None and cell_topography is not None:
            topo_values = np.asarray(cell_topography, dtype=float)
            topo_finite = topo_values[np.isfinite(topo_values)]
            if topo_finite.size:
                topo_coll = PolyCollection(
                    polygons,
                    array=topo_values,
                    cmap="terrain",
                    norm=Normalize(
                        vmin=float(np.nanmin(topo_finite)),
                        vmax=float(np.nanmax(topo_finite)),
                    ),
                    edgecolors="none",
                    alpha=0.34,
                    zorder=0,
                )
                ax.add_collection(topo_coll)
        facecolors = _drain_facecolors(drain, threshold=threshold, cmap=cmap, norm=norm)
        coll = PolyCollection(
            polygons,
            facecolors=facecolors,
            edgecolors=(0.25, 0.28, 0.32, 0.18),
            linewidths=0.18,
        )
        if clip_patch is not None:
            coll.set_clip_path(clip_patch)
        ax.add_collection(coll)
        mappable = ScalarMappable(norm=norm, cmap=cmap)
        _plot_geographic_lines(ax, river_network, origin, color="#3c78a8", lw=0.8, alpha=0.32)
        _plot_geographic_lines(ax, watershed_contour, origin, color="#17202a", lw=1.7, alpha=0.58)
        ax.scatter([0.0], [0.0], s=34, color="#17202a", edgecolors="white", linewidths=0.6)
        if bounds is not None:
            ax.set_xlim(bounds[0], bounds[2])
            ax.set_ylim(bounds[1], bounds[3])
        else:
            ax.autoscale_view()
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(
            f"{title}\ncellules actives={int(mask.sum())}",
            fontsize=11,
        )
        ax.set_xlabel("X relatif a l'exutoire (km)")
        ax.set_ylabel("Y relatif a l'exutoire (km)")
        ax.grid(True, ls=":", lw=0.35, color="#cfd8df")
    if mappable is not None:
        fig.colorbar(
            mappable,
            ax=axes.ravel().tolist(),
            fraction=0.035,
            pad=0.025,
            label="outflow_drain actif (m3/s, log)",
        )
    summary = (
        f"commun={int(true_positive.sum())}, "
        f"manques={int(false_negative.sum())}, exces={int(false_positive.sum())}"
    )
    source_label = _network_map_source_label(candidate)
    fig.suptitle(
        f"Drainage utilise par l'objectif spatial ({source_label}), clippe au bassin ({summary})"
    )
    fig.subplots_adjust(left=0.07, right=0.88, bottom=0.12, top=0.84, wspace=0.08)
    fig.savefig(path)
    plt.close(fig)


def _save_dem_context_map(truth_dir: Path | None, reference_root: Path, path: Path) -> None:
    if truth_dir is None:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import Normalize

    fallback_context = _mesh_context_from_truth_package(truth_dir)
    origin = None if fallback_context is None else fallback_context["origin"]
    polygons = None if fallback_context is None else fallback_context["polygons"]
    cell_topography = None if fallback_context is None else fallback_context["cell_topography"]
    topo = None
    source_label = "z_top_mean du maillage"
    watershed = None
    watershed_contour = None
    river_network = None

    if reference_root.is_dir():
        try:
            catalog, run = _open_first_run(reference_root)
        except Exception:
            catalog = None
        if catalog is not None:
            try:
                if origin is None:
                    try:
                        centroids, _ = mesh_cell_geometry(
                            run.mesh.vertices, run.mesh.face_node_connectivity
                        )
                        origin = _relative_origin(run, centroids)
                        polygons = _relative_polygons(_mesh_polygons(run), origin)
                        cell_topography = None
                    except Exception:
                        pass
                if origin is not None:
                    topo = _topography_context(run, origin)
                    if topo is not None:
                        source_label = "raster DEM watershed_dem"
                    watershed = _safe_geographic(run, "watershed")
                    watershed_contour = _safe_geographic(run, "watershed_contour")
                    river_network = _safe_geographic(run, "hydrographic_network_generated")
            finally:
                catalog.close()

    if origin is None or polygons is None:
        return

    bounds = _relative_gdf_bounds(watershed, origin) if watershed is not None else None
    if bounds is None:
        bounds = _polygon_bounds(polygons)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.8, 6.6), dpi=150)
    clip_patch = _watershed_clip_patch(watershed, origin, ax) if watershed is not None else None
    image = _plot_topography(ax, topo, clip_patch=clip_patch)
    mappable = image
    if topo is None and cell_topography is not None:
        topo_values = np.asarray(cell_topography, dtype=float)
        finite = topo_values[np.isfinite(topo_values)]
        if finite.size:
            coll = PolyCollection(
                polygons,
                array=topo_values,
                cmap="terrain",
                norm=Normalize(vmin=float(finite.min()), vmax=float(finite.max())),
                edgecolors=(0.18, 0.22, 0.27, 0.18),
                linewidths=0.15,
                alpha=0.82,
            )
            ax.add_collection(coll)
            mappable = coll
    else:
        mesh_overlay = PolyCollection(
            polygons,
            facecolors=(1.0, 1.0, 1.0, 0.0),
            edgecolors=(0.12, 0.16, 0.20, 0.14),
            linewidths=0.15,
        )
        ax.add_collection(mesh_overlay)

    _plot_geographic_lines(ax, river_network, origin, color="#276f93", lw=0.9, alpha=0.45)
    _plot_geographic_lines(ax, watershed_contour, origin, color="#17202a", lw=1.8, alpha=0.65)
    ax.scatter([0.0], [0.0], s=36, color="#17202a", edgecolors="white", linewidths=0.7)
    if bounds is not None:
        ax.set_xlim(bounds[0], bounds[2])
        ax.set_ylim(bounds[1], bounds[3])
    else:
        ax.autoscale_view()
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("X relatif a l'exutoire (km)")
    ax.set_ylabel("Y relatif a l'exutoire (km)")
    ax.grid(True, ls=":", lw=0.35, color="#cfd8df")
    ax.set_title(f"Contexte topographique ({source_label})")
    if mappable is not None:
        fig.colorbar(mappable, ax=ax, fraction=0.035, pad=0.025, label="Elevation (m)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _steady_drain_from_score_row(row: dict[str, str]) -> np.ndarray | None:
    source = str(row.get("network_map_source", "steady")).strip().lower()
    if source.startswith("transient"):
        transient_artifact = _score_file_path(row.get("transient_network_npz", ""))
        transient_drain = _outflow_drain_from_npz(transient_artifact)
        if transient_drain is not None:
            return transient_drain

    artifact = _score_file_path(row.get("steady_drain_npz", ""))
    steady_drain = _outflow_drain_from_npz(artifact)
    if steady_drain is not None:
        return steady_drain

    catalog_path = _score_catalog_path(row.get("steady_catalog", ""))
    if catalog_path is None or not catalog_path.is_dir():
        return None
    try:
        with SimulationCatalog(catalog_path) as catalog:
            run = catalog[catalog.resolve(row.get("steady_ref", "run_0001"))]
            return np.asarray(run.field("outflow_drain", timestep=-1), dtype=float).reshape(-1)
    except Exception:
        return None


def _outflow_drain_from_npz(artifact: Path | None) -> np.ndarray | None:
    if artifact is None or not artifact.is_file():
        return None
    try:
        with np.load(artifact) as data:
            return np.asarray(data["outflow_drain"], dtype=float).reshape(-1)
    except Exception:
        return None


def _network_map_source_label(row: dict[str, str]) -> str:
    source = str(row.get("network_map_source", "steady")).strip().lower()
    if source == "transient_last":
        return "dernier pas transitoire"
    if source == "transient_mean":
        return "moyenne transitoire"
    return "permanent"


def _mesh_context_from_truth_package(truth_dir: Path) -> dict[str, Any] | None:
    metadata = _read_json(truth_dir / "metadata.json")
    bundle = _score_file_path(metadata.get("mesh_bundle", ""))
    if bundle is None or not bundle.is_dir():
        return _mesh_context_from_cell_geometry(truth_dir)
    nodes_path = bundle / "nodes.csv"
    cells_path = bundle / "cells.csv"
    if not nodes_path.is_file() or not cells_path.is_file():
        return _mesh_context_from_cell_geometry(truth_dir)
    try:
        node_rows = _read_csv(nodes_path)
        cell_rows = sorted(
            _read_csv(cells_path),
            key=lambda row: int(float(str(row.get("cell_id", "0") or "0"))),
        )
        nodes = {
            int(float(row["node_id"])): (
                float(row["x"]),
                float(row["y"]),
            )
            for row in node_rows
        }
        polygons: list[np.ndarray] = []
        topo_values: list[float] = []
        for row in cell_rows:
            node_ids = []
            for key in ("n0", "n1", "n2", "n3"):
                raw = str(row.get(key, "") or "").strip()
                if raw:
                    node_ids.append(int(float(raw)))
            if len(node_ids) < 3:
                return None
            polygons.append(np.asarray([nodes[node_id] for node_id in node_ids], dtype=float))
            topo_values.append(_float(row.get("z_top_mean"), _float(row.get("z_top_centroid"))))
        geometry = np.load(truth_dir / "cell_geometry.npz")
        try:
            centroids = np.asarray(geometry["centroids"], dtype=float)
        finally:
            geometry.close()
        origin = _origin_from_config_or_centroids(centroids)
        return {
            "origin": origin,
            "polygons": _relative_polygons(polygons, origin),
            "cell_topography": np.asarray(topo_values, dtype=float),
        }
    except Exception:
        return _mesh_context_from_cell_geometry(truth_dir)


def _mesh_context_from_cell_geometry(truth_dir: Path) -> dict[str, Any] | None:
    geometry_path = truth_dir / "cell_geometry.npz"
    if not geometry_path.is_file():
        return None
    try:
        with np.load(geometry_path) as geometry:
            centroids = np.asarray(geometry["centroids"], dtype=float)
            areas = np.asarray(geometry["cell_area"], dtype=float).reshape(-1)
    except Exception:
        return None
    if centroids.ndim != 2 or centroids.shape[1] < 2 or centroids.shape[0] != areas.size:
        return None
    origin = _origin_from_config_or_centroids(centroids)
    polygons: list[np.ndarray] = []
    for (x, y), area in zip(centroids[:, :2], areas, strict=False):
        half_size = max(float(np.sqrt(area)) * 0.5, 1.0)
        polygons.append(
            np.asarray(
                [
                    [x - half_size, y - half_size],
                    [x + half_size, y - half_size],
                    [x + half_size, y + half_size],
                    [x - half_size, y + half_size],
                ],
                dtype=float,
            )
        )
    return {
        "origin": origin,
        "polygons": _relative_polygons(polygons, origin),
        "cell_topography": np.zeros(areas.size, dtype=float),
    }


def _origin_from_config_or_centroids(centroids: np.ndarray) -> tuple[float, float]:
    geographic = _read_toml(SOURCE_TRANSIENT_CONFIG).get("geographic", {})
    if isinstance(geographic, dict):
        catchment = geographic.get("catchment")
        if not isinstance(catchment, dict):
            catchment = {}
        x = _float(catchment.get("x_outlet"))
        y = _float(catchment.get("y_outlet"))
        if np.isfinite(x) and np.isfinite(y):
            return float(x), float(y)
    if centroids.size:
        return float(np.nanmean(centroids[:, 0])), float(np.nanmean(centroids[:, 1]))
    return 0.0, 0.0


def _polygon_bounds(polygons: list[np.ndarray]) -> tuple[float, float, float, float] | None:
    if not polygons:
        return None
    vertices = np.vstack([np.asarray(poly, dtype=float) for poly in polygons])
    if vertices.size == 0:
        return None
    margin = 0.06
    return (
        float(np.nanmin(vertices[:, 0])) - margin,
        float(np.nanmin(vertices[:, 1])) - margin,
        float(np.nanmax(vertices[:, 0])) + margin,
        float(np.nanmax(vertices[:, 1])) + margin,
    )


def _safe_geographic(run: Run, feature_name: str) -> Any | None:
    try:
        return run.geographic(feature_name)
    except Exception:
        return None


def _topography_context(run: Run, origin: tuple[float, float]) -> dict[str, Any] | None:
    try:
        raster = run.geographic_raster("watershed_dem")
    except Exception:
        return None
    data = np.asarray(raster.data, dtype=float)
    nodata = raster.nodata
    if nodata is not None:
        data = np.ma.masked_where(data == float(nodata), data)
    data = np.ma.masked_invalid(data)
    a, _, c, _, e, f = tuple(float(value) for value in raster.transform[:6])
    nrow, ncol = data.shape
    x0 = c
    x1 = c + a * ncol
    y0 = f
    y1 = f + e * nrow
    ox, oy = origin
    extent = [
        (min(x0, x1) - ox) / 1000.0,
        (max(x0, x1) - ox) / 1000.0,
        (min(y0, y1) - oy) / 1000.0,
        (max(y0, y1) - oy) / 1000.0,
    ]
    return {"data": data, "extent": extent}


def _plot_topography(ax: Any, topo: dict[str, Any] | None, *, clip_patch: Any = None) -> Any:
    if topo is None:
        return None
    image = ax.imshow(
        topo["data"],
        extent=topo["extent"],
        origin="upper",
        cmap="terrain",
        alpha=0.42,
        zorder=0,
    )
    if clip_patch is not None:
        image.set_clip_path(clip_patch)
    return image


def _drain_facecolors(drain: np.ndarray, *, threshold: float, cmap: Any, norm: Any) -> np.ndarray:
    values = np.asarray(drain, dtype=float).reshape(-1)
    colors = np.zeros((values.size, 4), dtype=float)
    inactive = values <= threshold
    colors[inactive] = (0.96, 0.97, 0.98, 0.16)
    active = ~inactive & np.isfinite(values)
    if np.any(active):
        colors[active] = cmap(norm(values[active]))
        colors[active, 3] = 0.88
    return colors


def _relative_gdf_bounds(
    gdf: Any | None, origin: tuple[float, float]
) -> tuple[float, float, float, float] | None:
    if gdf is None or len(gdf) == 0:
        return None
    bounds = np.asarray(gdf.total_bounds, dtype=float)
    ox, oy = origin
    margin = 0.06
    return (
        (bounds[0] - ox) / 1000.0 - margin,
        (bounds[1] - oy) / 1000.0 - margin,
        (bounds[2] - ox) / 1000.0 + margin,
        (bounds[3] - oy) / 1000.0 + margin,
    )


def _watershed_clip_patch(gdf: Any | None, origin: tuple[float, float], ax: Any) -> Any | None:
    if gdf is None or len(gdf) == 0:
        return None
    geom = gdf.geometry.iloc[0]
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda item: item.area)
    if geom.geom_type != "Polygon":
        return None
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath

    coords = (np.asarray(geom.exterior.coords, dtype=float) - np.asarray(origin)) / 1000.0
    codes = np.full(coords.shape[0], MplPath.LINETO, dtype=np.uint8)
    codes[0] = MplPath.MOVETO
    codes[-1] = MplPath.CLOSEPOLY
    return PathPatch(MplPath(coords, codes), transform=ax.transData, facecolor="none")


def _plot_geographic_lines(
    ax: Any,
    gdf: Any | None,
    origin: tuple[float, float],
    *,
    color: str,
    lw: float,
    alpha: float,
) -> None:
    if gdf is None or len(gdf) == 0:
        return
    offset = np.asarray(origin, dtype=float)
    for geom in gdf.geometry:
        for coords in _iter_geometry_line_coords(geom):
            rel = (np.asarray(coords, dtype=float) - offset) / 1000.0
            ax.plot(rel[:, 0], rel[:, 1], color=color, lw=lw, alpha=alpha, zorder=5)


def _iter_geometry_line_coords(geom: Any):
    if geom is None or geom.is_empty:
        return
    geom_type = geom.geom_type
    if geom_type in {"LineString", "LinearRing"}:
        yield np.asarray(geom.coords, dtype=float)
    elif geom_type == "Polygon":
        yield np.asarray(geom.exterior.coords, dtype=float)
        for ring in geom.interiors:
            yield np.asarray(ring.coords, dtype=float)
    elif geom_type.startswith("Multi") or geom_type == "GeometryCollection":
        for item in geom.geoms:
            yield from _iter_geometry_line_coords(item)


def _first_non_truth_candidate(score_rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in score_rows:
        if not _candidate_is_truth(row) and row.get("status") == "completed":
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


def _relative_origin(run: Run, centroids: np.ndarray) -> tuple[float, float]:
    try:
        x, y = run.outlet
        return float(x), float(y)
    except Exception:
        pass
    geographic = _read_toml(SOURCE_TRANSIENT_CONFIG).get("geographic", {})
    if isinstance(geographic, dict):
        catchment = geographic.get("catchment")
        if not isinstance(catchment, dict):
            catchment = {}
        x = _float(catchment.get("x_outlet"))
        y = _float(catchment.get("y_outlet"))
        if np.isfinite(x) and np.isfinite(y):
            return float(x), float(y)
    if centroids.size:
        return float(np.nanmean(centroids[:, 0])), float(np.nanmean(centroids[:, 1]))
    return 0.0, 0.0


def _relative_polygons(polygons: list[np.ndarray], origin: tuple[float, float]) -> list[np.ndarray]:
    offset = np.asarray(origin, dtype=float)
    return [(np.asarray(poly, dtype=float) - offset) / 1000.0 for poly in polygons]


def _candidate_is_truth(row: dict[str, str]) -> bool:
    candidate_id = str(row.get("candidate_id", ""))
    return candidate_id == "truth_identity" or candidate_id.startswith("truth")


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
    return _score_file_path(raw)


def _score_file_path(raw: Any) -> Path | None:
    if raw in (None, ""):
        return None
    path = Path(str(raw))
    if path.is_absolute():
        return path
    candidate = (PATH_BASE / path).resolve()
    if candidate.exists():
        return candidate
    return (Path.cwd() / path).resolve()


def _page(**kwargs: Any) -> str:
    return _blocks.build_page(
        **kwargs,
        page_title=PAGE_TITLE,
        web_root=WEB_ROOT,
    )


if __name__ == "__main__":
    main()
