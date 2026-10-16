"""Where an overview writes: the run directory of the overview, like any producer.

An overview is a producer of the project: its panels go to
``runs/<overview>/figures/`` and its web pages to
``runs/<overview>/report/``. ``<overview>`` is the ``[site] name`` of the
configuration, else ``[overview] name``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigMissingError
from hydromodpy.core.state.paths import runs_dir_for
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.results.storage.contract import (
    REPORT_INDEX_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_REPORT_DIRNAME,
)

REVIEW_DIRNAME = "review"
"""Folder of ``report/`` holding the compact, standard and audit review pages."""


def overview_name(site_name: str | None, overview_name: str | None) -> str:
    """Return the directory name of an overview: the site name, else its own name."""
    name = site_name or overview_name
    if not name:
        raise ConfigMissingError(
            "an overview writes to runs/<name>/: give the configuration a [site] name."
        )
    return str(name)


def overview_name_of_file(config_path: Path) -> str:
    """Return the directory name of the overview a TOML file configures, its base included."""
    tables: Mapping[str, Any] = load_toml_with_base_config(Path(config_path))
    return overview_name(
        (tables.get("site") or {}).get("name"), (tables.get("overview") or {}).get("name")
    )


def overview_run_dir_of(state: Any) -> Path:
    """Return the directory of the overview an overview state runs."""
    cfg = state.cfg
    name = overview_name(
        cfg.site.name if getattr(cfg, "site", None) is not None else None,
        getattr(cfg.overview, "name", None) if cfg.overview is not None else None,
    )
    return overview_run_dir(Path(state.workspace.project_root), name)


def overview_run_dir(project_root: Path, name: str) -> Path:
    """Return ``runs/<name>/``, the directory of one overview."""
    return runs_dir_for(Path(project_root)) / name


def overview_figures_dir(run_dir: Path) -> Path:
    """Return the panels folder of an overview."""
    return Path(run_dir) / RUN_FIGURES_DIRNAME


def overview_report_path(run_dir: Path) -> Path:
    """Return the web page of an overview."""
    return Path(run_dir) / RUN_REPORT_DIRNAME / REPORT_INDEX_FILENAME


def overview_review_dir(run_dir: Path) -> Path:
    """Return the folder of the review pages of an overview."""
    return Path(run_dir) / RUN_REPORT_DIRNAME / REVIEW_DIRNAME


__all__ = [
    "REVIEW_DIRNAME",
    "overview_figures_dir",
    "overview_name",
    "overview_name_of_file",
    "overview_report_path",
    "overview_review_dir",
    "overview_run_dir",
    "overview_run_dir_of",
]
