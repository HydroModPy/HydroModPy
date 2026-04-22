"""Workspace configuration with strict binary resolution.

Resolution order (first match wins):

1. **Explicit** — the TOML declares at least one of ``root``,
   ``catalog_path``, ``data_dir`` or ``simulations_dir`` under
   ``[workspace]``. A declared ``root`` derives the other three unless
   they are explicitly overridden.
2. **Env var** — ``HYDROMODPY_WORKSPACE`` is set and points to a
   directory.
3. **Scaffold** — the TOML lives at
   ``<workspace>/projects/<name>/project.toml`` and the grand-grand-parent
   contains a ``hydromodpy.duckdb`` file or a ``data/`` directory.

Anything else raises :class:`WorkspaceError` with an actionable hint.
There is no walk-up auto-discovery, no silent fallback to
``project_root``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.workspace.exceptions import WorkspaceError

ResolutionSource = Literal["explicit", "env", "scaffold"]


class WorkspaceConfig(HydroModelBase):
    """Strict-binary workspace configuration.

    The canonical workspace layout is::

        <workspace>/
            hydromodpy.duckdb
            data/
                cache.duckdb
            simulations/
                <uuid>.zarr/
            projects/
                <name>/
                    project.toml   <- TOML lives here when using scaffold

    Fields under ``[workspace]``:

    ``project_root`` (required, legacy)
        Directory of the project TOML. Usually auto-derived from the TOML
        location by the loader.

    ``root`` (explicit workspace override)
        When set, the workspace root. Derives ``catalog_path``,
        ``data_dir`` and ``simulations_dir`` unless those are also set.

    ``catalog_path`` / ``data_dir`` / ``simulations_dir``
        Per-component explicit overrides. Any of these three triggers the
        "explicit" resolution branch and bypasses the scaffold and env
        lookups.

    ``output_root``
        Optional redirect for heavy outputs (``.solver_scratch/`` and
        per-run ``figures/``). Defaults to ``project_root``.
    """

    model_config = ConfigDict(extra="forbid")

    project_root: Annotated[Path, Profile.USER] = Field(
        description=("Path to the project directory. Auto-derived from TOML location when absent."),
    )

    root: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Explicit workspace root. When set, derives catalog_path, "
            "data_dir and simulations_dir unless those are overridden."
        ),
    )

    catalog_path: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description=("Explicit path to hydromodpy.duckdb. Defaults to <root>/hydromodpy.duckdb."),
    )

    data_dir: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description=("Explicit path to the workspace data directory. Defaults to <root>/data."),
    )

    simulations_dir: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Explicit path to the simulations Zarr directory. Defaults to <root>/simulations."
        ),
    )

    output_root: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Root directory for per-project outputs (.solver_scratch/, "
            "figures/). Defaults to project_root when not set. "
            "Use this to redirect heavy outputs to a separate disk."
        ),
    )

    @model_validator(mode="after")
    def _resolve(self) -> WorkspaceConfig:
        """Resolve to absolute paths using the strict binary contract."""
        project_root = Path(self.project_root).expanduser().resolve()
        object.__setattr__(self, "project_root", project_root)

        root, source = _resolve_root(
            project_root=project_root,
            root=self.root,
            catalog_path=self.catalog_path,
            data_dir=self.data_dir,
            simulations_dir=self.simulations_dir,
        )

        object.__setattr__(self, "root", root)
        object.__setattr__(
            self,
            "catalog_path",
            _finalize(self.catalog_path, root / "hydromodpy.duckdb"),
        )
        object.__setattr__(
            self,
            "data_dir",
            _finalize(self.data_dir, root / "data"),
        )
        object.__setattr__(
            self,
            "simulations_dir",
            _finalize(self.simulations_dir, root / "simulations"),
        )
        if self.output_root is not None:
            object.__setattr__(
                self,
                "output_root",
                Path(self.output_root).expanduser().resolve(),
            )
        object.__setattr__(self, "_resolution_source", source)
        return self

    # -- Resolution source -------------------------------------------------

    @property
    def resolution_source(self) -> ResolutionSource:
        """How the workspace was located ("explicit", "env", "scaffold")."""
        return getattr(self, "_resolution_source", "explicit")

    # -- Back-compat shims -------------------------------------------------
    #
    # ``workspace_root`` was the historical alias for ``root``. Keep the
    # property so consumers that still read it (e.g. legacy solver code)
    # keep working during the v0.6 sweep.

    @property
    def workspace_root(self) -> Path:
        return self.root

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


def _resolve_root(
    *,
    project_root: Path,
    root: Path | None,
    catalog_path: Path | None,
    data_dir: Path | None,
    simulations_dir: Path | None,
) -> tuple[Path, ResolutionSource]:
    """Apply the strict binary resolution contract.

    Returns ``(workspace_root, source)``.
    """
    # 1. Explicit [workspace] declaration wins.
    if root is not None:
        return Path(root).expanduser().resolve(), "explicit"
    if any(p is not None for p in (catalog_path, data_dir, simulations_dir)):
        # At least one component is explicit — derive the root from the
        # first one that is set (catalog_path first, then data_dir, then
        # simulations_dir), using its parent as the workspace root.
        for component, _default_name in (
            (catalog_path, "hydromodpy.duckdb"),
            (data_dir, "data"),
            (simulations_dir, "simulations"),
        ):
            if component is not None:
                derived = Path(component).expanduser().resolve().parent
                return derived, "explicit"

    # 2. Env var.
    env_root = os.environ.get("HYDROMODPY_WORKSPACE")
    if env_root:
        return Path(env_root).expanduser().resolve(), "env"

    # 3. Scaffold layout — <workspace>/projects/<name>/project.toml.
    if project_root.parent.name == "projects":
        candidate = project_root.parent.parent
        if (candidate / "hydromodpy.duckdb").exists() or (candidate / "data").is_dir():
            return candidate.resolve(), "scaffold"

    raise WorkspaceError(_format_hint(project_root))


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
