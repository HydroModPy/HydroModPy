"""Where an overview writes: the run directory of the overview, like any producer.

An overview is a producer of the project: its panels go to
``runs/<overview>/figures/`` and its pages, written after the seal, to
``runs/<overview>/report/``. ``<overview>`` is the ``[site] name`` of the
configuration, else ``[overview] name``. An overview claims its directory
through the attempt protocol, so a second overview of the same name is
``runs/<overview>.v2/``: the directory of an overview is the latest version
of its name.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import ConfigMissingError
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.results.storage.attempt import latest_version_dir
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

if TYPE_CHECKING:
    from hydromodpy.core.contracts.overview import DataOverviewState


def overview_name(site_name: str | None, overview_name: str | None) -> str:
    """Return the directory name of an overview: the site name, else its own name."""
    name = site_name or overview_name
    if not name:
        raise ConfigMissingError(
            "an overview writes to runs/<name>/: give the configuration a [site] name."
        )
    return str(name)


def overview_run_dir_of(state: DataOverviewState) -> Path:
    """Return the directory of the overview an overview state runs."""
    cfg = state.cfg
    name = overview_name(
        cfg.site.name if getattr(cfg, "site", None) is not None else None,
        getattr(cfg.overview, "name", None) if cfg.overview is not None else None,
    )
    return overview_run_dir(Path(state.workspace.project_root), name)


def overview_run_dir(project_root: Path, name: str) -> Path:
    """Return the directory of the overview *name*: its latest version, else ``runs/<name>/``."""
    latest = latest_version_dir(Path(project_root), name)
    return latest if latest is not None else runs_dir_for(Path(project_root)) / name


def overview_figures_dir(run_dir: Path) -> Path:
    """Return the panels folder of an overview."""
    return Path(run_dir) / RUN_FIGURES_DIRNAME


__all__ = [
    "overview_figures_dir",
    "overview_name",
    "overview_run_dir",
    "overview_run_dir_of",
]
