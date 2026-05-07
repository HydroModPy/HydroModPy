"""Workspace configuration with project-local result catalogs.

Resolution order (first match wins):

1. **Explicit** - the TOML declares ``root`` or ``data_dir`` under
   ``[workspace]``. A declared ``root`` derives the shared data directory
   unless ``data_dir`` is explicitly overridden.
2. **Env var** - ``HYDROMODPY_WORKSPACE`` is set and points to a
   directory used as the shared data workspace.
3. **Scaffold** - the TOML lives at
   ``<workspace>/projects/<name>/project.toml`` and the grand-grand-parent
   contains a ``data/`` directory.
4. **Standalone project** - the project directory itself is used as the
   shared data workspace.

Result catalogs are project-local by default: ``catalog_path`` resolves to
``<project_root>/hydromodpy.duckdb`` and ``simulations_dir`` resolves to
``<project_root>/simulations``. The shared workspace root only owns input
data caches.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PrivateAttr, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

ResolutionSource = Literal["explicit", "env", "scaffold", "project"]


class WorkspaceConfig(HydroModelBase):
    """Strict-binary workspace configuration.

    The canonical workspace layout is::

        <workspace>/
            data/
                cache.duckdb
            projects/
                <name>/
                    project.toml   <- TOML lives here when using scaffold
                    hydromodpy.duckdb
                    simulations/
                        <basename>.zarr/ or <basename>.zarr.zip

    Fields under ``[workspace]``:

    ``project_root`` (required)
        Directory of the project TOML. Usually auto-derived from the TOML
        location by the loader.

    ``root`` (explicit workspace override)
        When set, the shared data workspace root. Derives ``data_dir``
        unless it is explicitly overridden.

    ``catalog_path`` / ``data_dir`` / ``simulations_dir``
        Per-component explicit overrides. ``catalog_path`` and
        ``simulations_dir`` are project-local by default.

    ``output_root``
        Optional redirect for heavy outputs (``.solver_scratch/`` and
        per-run ``figures/``). Defaults to ``project_root``.
    """

    project_root: Annotated[Path, Profile.USER] = Field(
        description="Path to the project directory. Required in TOML configs.",
        examples=["."],
    )

    root: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Explicit shared data workspace root. When set, derives data_dir unless "
            "it is overridden. Result catalogs stay project-local by default."
        ),
        examples=["../.."],
    )

    catalog_path: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Explicit path to the project hydromodpy.duckdb. Defaults to "
            "<project_root>/hydromodpy.duckdb."
        ),
    )

    data_dir: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description=("Explicit path to the workspace data directory. Defaults to <root>/data."),
    )

    simulations_dir: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Explicit path to the simulations Zarr directory. Defaults to "
            "<project_root>/simulations."
        ),
    )

    output_root: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Root directory for per-project outputs (.solver_scratch/, "
            "figures/). Defaults to project_root when not set. "
            "Use this to redirect heavy outputs to a separate disk."
        ),
        examples=["outputs/run_a"],
    )

    _resolution_source: ResolutionSource = PrivateAttr(default="explicit")

    @model_validator(mode="after")
    def _resolve(self) -> WorkspaceConfig:
        """Resolve to absolute paths using the strict binary contract."""
        project_root = Path(self.project_root).expanduser().resolve()
        _set_if_changed(self, "project_root", project_root)

        root, source = _resolve_root(
            project_root=project_root,
            root=self.root,
            catalog_path=self.catalog_path,
            data_dir=self.data_dir,
            simulations_dir=self.simulations_dir,
        )

        _set_if_changed(self, "root", root)
        _set_if_changed(
            self,
            "catalog_path",
            _finalize(self.catalog_path, project_root / "hydromodpy.duckdb"),
        )
        _set_if_changed(self, "data_dir", _finalize(self.data_dir, root / "data"))
        _set_if_changed(
            self,
            "simulations_dir",
            _finalize(self.simulations_dir, project_root / "simulations"),
        )
        if self.output_root is not None:
            _set_if_changed(self, "output_root", Path(self.output_root).expanduser().resolve())
        self._resolution_source = source
        return self

    # -- Resolution source -------------------------------------------------

    @property
    def resolution_source(self) -> ResolutionSource:
        """How the shared data workspace was located."""
        return getattr(self, "_resolution_source", "explicit")

    @property
    def _effective_output_root(self) -> Path:
        """Root for result directories: output_root if set, else project_root."""
        if self.output_root is not None:
            return self.output_root
        return self.project_root

    @property
    def catch_name(self) -> str:
        """Project name derived from the project directory name."""
        return self.project_root.name

    @property
    def solver_scratch_folder(self) -> Path:
        """Path to the temporary solver scratch directory."""
        return self._effective_output_root / ".solver_scratch"

    @property
    def data_path(self) -> Path:
        """Path to the shared data folder (always resolved)."""
        return self.data_dir


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _finalize(value: Path | None, default: Path) -> Path:
    """Return an absolute resolved path, falling back to ``default``."""
    path = Path(value).expanduser() if value is not None else default
    return path.resolve()


def _set_if_changed(model: WorkspaceConfig, name: str, value: Path) -> None:
    if getattr(model, name) != value:
        setattr(model, name, value)


def _resolve_root(
    *,
    project_root: Path,
    root: Path | None,
    catalog_path: Path | None,
    data_dir: Path | None,
    simulations_dir: Path | None,
) -> tuple[Path, ResolutionSource]:
    """Resolve the shared data workspace root.

    ``catalog_path`` and ``simulations_dir`` are accepted for signature
    stability, but they do not define the shared data root anymore.
    """
    if root is not None:
        return Path(root).expanduser().resolve(), "explicit"
    if data_dir is not None:
        return Path(data_dir).expanduser().resolve().parent, "explicit"

    env_root = os.environ.get("HYDROMODPY_WORKSPACE")
    if env_root:
        return Path(env_root).expanduser().resolve(), "env"

    if project_root.parent.name == "projects":
        candidate = project_root.parent.parent
        if (candidate / "data").is_dir():
            return candidate.resolve(), "scaffold"

    if catalog_path is not None or simulations_dir is not None:
        return project_root, "explicit"

    return project_root, "project"


def _format_hint(project_root: Path) -> str:
    return (
        f"Cannot locate a HydroModPy workspace for project at {project_root}.\n"
        "Pick one of:\n"
        "  (a) scaffold: run `hmp init <workspace-dir>` then place\n"
        "      this TOML at <workspace>/projects/<name>/project.toml\n"
        "  (b) env var:  export HYDROMODPY_WORKSPACE=/path/to/workspace\n"
        "  (c) explicit: add to [workspace]:\n"
        "          root = '/path/to/workspace'\n"
        "        (or per-component: catalog_path, data_dir, simulations_dir)"
    )
