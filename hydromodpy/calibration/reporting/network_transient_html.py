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


def _page(**kwargs: Any) -> str:
    return _blocks.build_page(
        **kwargs,
        page_title=PAGE_TITLE,
        web_root=WEB_ROOT,
    )


if __name__ == "__main__":
    main()
