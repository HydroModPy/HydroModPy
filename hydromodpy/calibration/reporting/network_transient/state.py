"""Mutable defaults for the network/transient HTML report.

The B0 example project (``examples/projects/12_calibration_network_transient_b0``)
is the historical default. Paths are loaded from
``validation_cases/calibration/network_transient_b0/fixture.toml`` at import
time so the validation fixture remains the source of truth.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
B0_FIXTURE_PATH = (
    REPO_ROOT / "validation_cases" / "calibration" / "network_transient_b0" / "fixture.toml"
)


@dataclass(frozen=True)
class _B0Defaults:
    """Resolved B0 default paths and titles."""

    example_root: Path
    source_transient_config: Path
    real_runs_subdir: str
    web_subdir: str
    reference_run_name: str
    steady_summary_csv: str
    page_title: str
    truth_package_candidates: tuple[str, ...]
    score_table_candidates: tuple[str, ...]


def _load_fixture() -> _B0Defaults:
    """Load the B0 validation fixture (TOML) and resolve to absolute paths."""
    payload: dict = {}
    if B0_FIXTURE_PATH.is_file():
        payload = tomllib.loads(B0_FIXTURE_PATH.read_text(encoding="utf-8"))
    paths = payload.get("paths", {}) if isinstance(payload.get("paths"), dict) else {}
    report = payload.get("report", {}) if isinstance(payload.get("report"), dict) else {}
    truth = (
        payload.get("truth_packages", {}) if isinstance(payload.get("truth_packages"), dict) else {}
    )
    scores = (
        payload.get("score_tables", {}) if isinstance(payload.get("score_tables"), dict) else {}
    )

    example_root = REPO_ROOT / paths.get(
        "example_root", "examples/projects/12_calibration_network_transient_b0"
    )
    source_cfg = REPO_ROOT / paths.get(
        "source_transient_config",
        "examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/base_site_01_mf6_bouss_transient.toml",
    )
    return _B0Defaults(
        example_root=example_root,
        source_transient_config=source_cfg,
        real_runs_subdir=str(paths.get("real_runs_subdir", "outputs/real_runs")),
        web_subdir=str(paths.get("web_subdir", "web")),
        reference_run_name=str(
            paths.get("reference_run_name", "candidate_mK_0p65_Sy_0p05_steady_mf6")
        ),
        steady_summary_csv=str(
            paths.get("steady_summary_csv", "steady_mK_network_extent_summary.csv")
        ),
        page_title=str(
            report.get("page_title", "B0 - calibration MF6 reseau permanent + debit transitoire")
        ),
        truth_package_candidates=tuple(
            str(name)
            for name in truth.get(
                "candidates",
                ["site_01_truth_package_mK_0p65", "site_01_truth_package"],
            )
        ),
        score_table_candidates=tuple(
            str(name)
            for name in scores.get(
                "candidates",
                [
                    "site_01_parameter_grid_scores_mK_0p65.csv",
                    "site_01_candidate_scores_mK_0p65.csv",
                    "site_01_candidate_scores.csv",
                    "site_01_parameter_grid_light_scores_mK_0p65.csv",
                ],
            )
        ),
    )


def report_facade():
    """Return the ``network_transient_html`` facade module (live runtime config).

    The facade rebinds ``SOURCE_TRANSIENT_CONFIG``, ``PATH_BASE``, ``REAL_ROOT``
    and ``REFERENCE_RUN_ROOT`` at run time (``_configure_from_args``). Sibling
    modules read them through this accessor so a single call-time import keeps
    them a leaf: the facade imports this package at load, so it can only be
    resolved once fully initialized.
    """
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html


_B0 = _load_fixture()

DEFAULT_EXAMPLE_ROOT = _B0.example_root
ROOT = DEFAULT_EXAMPLE_ROOT
SOURCE_TRANSIENT_CONFIG = _B0.source_transient_config
REAL_ROOT = ROOT / _B0.real_runs_subdir
WEB_ROOT = REAL_ROOT / _B0.web_subdir
FIGURE_ROOT = WEB_ROOT / "figures"
PAGE_TITLE = _B0.page_title
TRUTH_PACKAGE_CANDIDATES = tuple(REAL_ROOT / name for name in _B0.truth_package_candidates)
SCORE_TABLE_CANDIDATES = tuple(REAL_ROOT / name for name in _B0.score_table_candidates)
PATH_BASE = ROOT
REFERENCE_RUN_ROOT = REAL_ROOT / _B0.reference_run_name
STEADY_SUMMARY_CSV = REAL_ROOT / _B0.steady_summary_csv
