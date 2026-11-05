"""Open a project that already exists, and show it.

``open_project`` builds a :class:`~hydromodpy.project.facade.Project` on a
project directory without validating or building anything;
``configure_opened`` configures it from its ``project.toml`` the first time a
model verb needs a configuration; ``resolve_config`` normalizes the polymorphic
config input of ``Project(...)``; ``project_html`` is the notebook view.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import ConfigMissingError
from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME, resolve_project_root
from hydromodpy.project import phases as project_phases
from hydromodpy.project.catalog import ProjectCatalog
from hydromodpy.project.runner import ProjectRunner
from hydromodpy.project.state import ProjectState

if TYPE_CHECKING:
    from hydromodpy.project.facade import Project
    from hydromodpy.results.catalog import Catalog


def resolve_config(config: str | Path | object | dict) -> object:
    """Normalize a polymorphic config input to a path or ``HydroModPyConfig``.

    ``dict`` -> validated config; JSON string (starts with ``{``) -> validated
    config; a TOML path or an already-built config object passes through.
    """
    if isinstance(config, Mapping):
        from hydromodpy.config import HydroModPyConfig

        return HydroModPyConfig.from_dict(dict(config))
    if isinstance(config, str) and config.lstrip().startswith("{"):
        from hydromodpy.config import HydroModPyConfig

        return HydroModPyConfig.from_json(config)
    return config


def configure_opened(project: Project) -> None:
    """Configure a project opened on its directory from its ``project.toml``.

    A ``[sites]`` project has one configuration per case, written by its
    plan; it is read and launched, never configured as one model.
    """
    from hydromodpy.config.sites.expansion import SitesProjectError, find_sites_file
    from hydromodpy.core.toml_io.loader import read_toml_chain

    state = project.__dict__["_state"]
    marker = state.root / PROJECT_MARKER_FILENAME
    if not marker.is_file():
        raise ConfigMissingError(
            f"{state.root} holds no {PROJECT_MARKER_FILENAME}: an opened project builds "
            "its model from it. Open a configuration with hmp.Project(<file>.toml)."
        )
    if find_sites_file(read_toml_chain(marker)) is not None:
        raise SitesProjectError(
            f"{marker} is a [sites] project: each case is configured by its plan. Read "
            "it with proj.cases, launch it with proj.launch(), or build one case with "
            "hmp.Project('plan/<hash>/<case>.toml')."
        )
    try:
        project_phases.configure(project, marker, solver=None, headless=False, no_display=False)
    except BaseException:
        state.cfg = None
        raise


def open_project(path: str | Path) -> Project:
    """Open the project a directory, or a file inside it, belongs to, read only.

    The project root is the folder of ``project.toml`` at or above *path*.
    Nothing is validated or built: the project reads its plan, its runs and
    its sessions from the disk, and reads ``project.toml`` only when a model
    verb (``simulate``, ``prepare``, ``config`` ...) needs a configuration.
    """
    start = Path(path).expanduser().resolve()
    root = resolve_project_root(start.parent if start.is_file() else start).resolve()
    from hydromodpy.project.facade import Project

    project = object.__new__(Project)
    object.__setattr__(project, "_state", ProjectState(root=root))
    object.__setattr__(project, "_runner", ProjectRunner(project))
    object.__setattr__(project, "_catalog", ProjectCatalog(project))
    return project


def project_html(project: Project) -> str:
    """Return the HTML table a notebook shows for *project*."""
    if project._config_path is not None:
        source_label = project._config_path.name
        project_name = project._config_path.parent.name
    else:
        source_label = "&lt;in-memory&gt;"
        project_name = getattr(project, "_project_name", "") or "&mdash;"
    runs = project._run_history
    n_runs = len(runs)
    last_run = runs[-1] if runs else None
    rows: list[tuple[str, str]] = [
        ("config", f"<code>{source_label}</code>"),
        ("project", project_name),
        ("solver", str(project._state.solver or "&mdash;")),
        ("headless", "yes" if project._state.headless else "no"),
        ("runs", str(n_runs)),
        (
            "last run",
            f"<code>{last_run.sim_id[:8]}</code> ({last_run.name})"
            if last_run is not None
            else "&mdash;",
        ),
    ]
    body = "".join(
        f"<tr><th style='text-align:left;padding-right:8px'>{k}</th><td>{v}</td></tr>"
        for k, v in rows
    )
    return (
        "<div><b>Project</b>"
        "<table style='font-size:0.85em;border-collapse:collapse'>"
        f"{body}</table></div>"
    )


def refreshed_index(project: Project) -> Catalog:
    """Bring the index of *project* up to date with its run directories; return it, open."""
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.indexer import index_new_runs

    root = project.root
    report = index_new_runs(root)
    store = project._store
    if store is not None and not store.closed and report.unchanged:
        return store
    if store is not None:
        store.close()
    project._store = Catalog(root)
    return project._store


def project_repr(project: Project) -> str:
    """Return ``Project('<root>')``, or the name of the config file of a project built from one."""
    if project._state.root is not None:
        return f"Project({str(project._state.root)!r})"
    source = project._config_path.name if project._config_path else "<in-memory>"
    return f"Project({source!r})"
