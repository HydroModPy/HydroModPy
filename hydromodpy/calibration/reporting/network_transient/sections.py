"""HTML section builders and metric summaries for the network/transient report.

Concrete bodies live in
``hydromodpy/calibration/reporting/network_transient_html.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "artifact_contract_summary",
    "best_candidate_summary",
    "build_page",
    "conductivity_context",
    "configuration_metrics",
    "figure_card",
    "q_total_release_series",
    "score_catalog_path",
    "score_file_path",
    "source_k_values",
    "truth_label",
]


def build_page(**kwargs) -> str:
    """Render the full HTML page (re-export of network_transient_html._page)."""
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._page(**kwargs)


def truth_label(truth_dir: Path | None) -> str:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._truth_label(truth_dir)


def artifact_contract_summary(report) -> str:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._artifact_contract_summary(report)


def best_candidate_summary(score_rows: list[dict[str, str]], truth_dir: Path | None) -> str:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._best_candidate_summary(score_rows, truth_dir)


def configuration_metrics(normalization: dict[str, Any], truth_dir: Path | None) -> str:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._configuration_metrics(normalization, truth_dir)


def conductivity_context(metadata: dict[str, Any]) -> dict[str, float]:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._conductivity_context(metadata)


def source_k_values():
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._source_k_values()


def figure_card(path: Path | None, title: str, caption: str) -> str:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._figure_card(path, title, caption)


def q_total_release_series(**kwargs) -> dict[str, list[float]]:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._q_total_release_series(**kwargs)


def score_catalog_path(raw) -> Path | None:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._score_catalog_path(raw)


def score_file_path(raw) -> Path | None:
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html._score_file_path(raw)
