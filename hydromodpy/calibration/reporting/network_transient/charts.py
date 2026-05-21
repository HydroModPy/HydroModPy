"""Matplotlib figure builders for the network/transient HTML report.

This module exposes the figure-generation surface used by ``assemble``. Each
figure helper writes a PNG to a caller-supplied path. The concrete bodies live
in ``hydromodpy/calibration/reporting/network_transient_html.py`` to preserve
the historical module-level globals mutated by ``_configure_from_args``.
"""

from __future__ import annotations

__all__ = [
    "generate_figures",
    "prune_stale_figures",
    "save_dem_context_map",
    "save_objective_parameter_maps",
    "save_objective_profile_cuts",
    "save_outflow_map_grid",
    "save_q_timeseries_figure",
    "save_recharge_chronicle_figure",
    "save_steady_balance_didactic",
    "save_watershed_id_card",
]


def generate_figures(**kwargs) -> dict:
    """Generate every figure required by the report, returning their paths."""
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._generate_figures(**kwargs)


def prune_stale_figures(figures: dict) -> None:
    """Delete obsolete PNGs from the figure root."""
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._prune_stale_figures(figures)


def save_watershed_id_card(root, path) -> None:
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._save_watershed_id_card(root, path)


def save_dem_context_map(truth_dir, reference_root, path) -> None:
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._save_dem_context_map(truth_dir, reference_root, path)


def save_steady_balance_didactic(truth_dir, rows, path) -> None:
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._save_steady_balance_didactic(truth_dir, rows, path)


def save_recharge_chronicle_figure(path) -> None:
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._save_recharge_chronicle_figure(path)


def save_q_timeseries_figure(score_rows, truth_q, path) -> None:
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._save_q_timeseries_figure(score_rows, truth_q, path)


def save_objective_parameter_maps(truth_dir, score_rows, path) -> None:
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._save_objective_parameter_maps(truth_dir, score_rows, path)


def save_objective_profile_cuts(truth_dir, score_rows, path) -> None:
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._save_objective_profile_cuts(truth_dir, score_rows, path)


def save_outflow_map_grid(truth_dir, score_rows, path) -> None:
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html._save_outflow_map_grid(truth_dir, score_rows, path)
