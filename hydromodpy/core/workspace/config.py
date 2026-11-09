"""Workspace configuration with project-local result catalogs.

The project root is never written in a file. The config loader sets
``project_root`` from where the file sits: the folder that holds
``project.toml`` above it, else the folder of the file itself. A Python
caller may pass it. It is a runtime attribute: never written back to TOML
and never part of the config hash.

Resolution order of the shared data workspace (first match wins):

1. **Explicit** - the TOML declares ``root`` or ``data_dir`` under
   ``[workspace]``. A declared ``root`` derives the shared data directory
   unless ``data_dir`` is explicitly overridden.
2. **Env var** - ``HMP_WORKSPACE`` is set and points to a
   directory used as the shared data workspace.
3. **Scaffold** - the TOML lives at
   ``<workspace>/projects/<name>/project.toml`` and the grand-grand-parent
   contains a ``data/`` directory.
4. **Standalone project** - the project directory itself is used as the
   shared data workspace.

Results are always project-local: ``catalog_path`` is
``<project_root>/.hmp/index.duckdb`` and ``runs_dir`` is
``<project_root>/runs``. The shared workspace root only owns input data
caches.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import Field, PrivateAttr, computed_field, model_validator
from upath import UPath

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, catalog_path_for, runs_dir_for
from hydromodpy.core.workspace.workspace_toml import refuse_a_newer_workspace

ResolutionSource = Literal["explicit", "env", "scaffold", "project"]
_SAFE_FILENAME_WINDOWS_DRIVE = "\uf03a"
_SAFE_FILENAME_WINDOWS_SEPARATOR = "\uf05c"


class WorkspaceConfig(HydroModelBase):
    """Strict-binary workspace configuration.

    The canonical workspace layout is::

        <workspace>/
            workspace.toml
            data/
                <variable>/<file> and its <file>.json sidecar
            projects/
                <name>/
                    project.toml   <- TOML lives here when using scaffold
                    runs/<run>/
                    .hmp/index.duckdb

    Fields under ``[workspace]``:

    ``project_root`` (runtime only)
        Directory of the project. Set by the loader from the location of the
        file; refused when a file writes it.

    ``root`` (explicit workspace override)
        When set, the shared data workspace root. Derives ``data_dir``
        unless it is explicitly overridden.

    ``data_dir``
        Explicit override of the folder the input data are read from. The index
        (``catalog_path``) and the runs (``runs_dir``) are read-only properties,
        fixed by the storage layout contract.

    Every output of a run lives in ``runs/<run>/``. The solver scratch of a
    run is ``HMP_SCRATCH_ROOT``, else the default of the launcher.
    """

    project_root: Annotated[Path | UPath, Profile.DEV] = Field(
        description=(
            "Folder of the project, set by the loader: the folder that holds "
            "project.toml, else the folder of the file. Never written in a file."
        ),
        json_schema_extra=field_metadata(toml_exclude=True),
    )

    root: Annotated[Path | UPath | None, Profile.USER] = Field(
        default=None,
        description=(
            "Explicit shared data workspace root. When set, derives data_dir unless "
            "it is overridden. Result catalogs stay project-local by default."
        ),
        examples=["../.."],
    )

    data_dir: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Folder the input data are read from and downloads are cached in. "
            "Unset, it is <root>/data."
        ),
    )

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "catalog_path": (
            "the index of a project is <project>/.hmp/index.duckdb, fixed by the storage "
            "layout contract (docs/source/contribute/architecture/storage-layout.rst). "
            "Delete the key."
        ),
        "runs_dir": (
            "the runs of a project are in <project>/runs/, fixed by the storage layout "
            "contract (docs/source/contribute/architecture/storage-layout.rst). Delete the key."
        ),
        "output_root": (
            "it has no replacement: the outputs of a run live in runs/<run>/, and the "
            "solver scratch is HMP_SCRATCH_ROOT or the default of the launcher."
        ),
        "solver_scratch_folder": (
            "the solver scratch is HMP_SCRATCH_ROOT or the default of the launcher."
        ),
        "share_folder": "it has no replacement: the outputs of a run live in runs/<run>/.",
        "catch_name": "the name of the catchment is [site] name.",
    }

    _resolution_source: ResolutionSource = PrivateAttr(default="explicit")

    @model_validator(mode="after")
    def _resolve(self) -> WorkspaceConfig:
        """Resolve to absolute paths using the strict binary contract."""
        for field_name in (
            "project_root",
            "root",
            "data_dir",
        ):
            _reject_safe_filename_path(field_name, getattr(self, field_name))

        project_root = Path(self.project_root).expanduser().resolve()
        _set_if_changed(self, "project_root", project_root)

        root, source = _resolve_root(
            project_root=project_root,
            root=self.root,
            data_dir=self.data_dir,
        )

        refuse_a_newer_workspace(root)
        _set_if_changed(self, "root", root)
        _set_if_changed(self, "data_dir", _finalize(self.data_dir, root / "data"))
        self._resolution_source = source
        return self

    # -- Resolution source -------------------------------------------------

    @property
    def resolution_source(self) -> ResolutionSource:
        """How the shared data workspace was located."""
        return getattr(self, "_resolution_source", "explicit")

    @property
    def catalog_path(self) -> Path:
        """The project index, ``<project_root>/.hmp/index.duckdb``."""
        return catalog_path_for(Path(self.project_root))

    @property
    def runs_dir(self) -> Path:
        """The folder of the runs, ``<project_root>/runs``."""
        return runs_dir_for(Path(self.project_root))

    @computed_field
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


def _reject_safe_filename_path(name: str, value: object | None) -> None:
    """Reject paths that were already encoded for filename-safe storage."""
    if value is None:
        return
    text = str(value)
    if _SAFE_FILENAME_WINDOWS_DRIVE in text or _SAFE_FILENAME_WINDOWS_SEPARATOR in text:
        raise ValueError(
            f"workspace.{name} contains private-use characters that look like a "
            "Windows path encoded as a safe filename. Pass a real path, such as "
            r"'C:\path\to\workspace', or a project-relative path."
        )


def _set_if_changed(model: WorkspaceConfig, name: str, value: Path) -> None:
    if getattr(model, name) != value:
        setattr(model, name, value)


def _resolve_root(
    *,
    project_root: Path,
    root: Path | None,
    data_dir: Path | None,
) -> tuple[Path, ResolutionSource]:
    """Resolve the shared data workspace root."""
    if root is not None:
        return Path(root).expanduser().resolve(), "explicit"
    if data_dir is not None:
        return Path(data_dir).expanduser().resolve().parent, "explicit"

    env_root = os.environ.get("HMP_WORKSPACE")
    if env_root:
        return Path(env_root).expanduser().resolve(), "env"

    if project_root.parent.name == "projects":
        candidate = project_root.parent.parent
        if (candidate / "data").is_dir():
            return candidate.resolve(), "scaffold"

    return project_root, "project"


def _format_hint(project_root: Path) -> str:
    return (
        f"Cannot locate a HydroModPy workspace for project at {project_root}.\n"
        "Pick one of:\n"
        "  (a) scaffold: run `hmp workspace init <workspace-dir>` then place\n"
        f"      this TOML at <workspace>/projects/<name>/{PROJECT_MARKER_FILENAME}\n"
        "  (b) env var:  export HMP_WORKSPACE=/path/to/workspace\n"
        "  (c) explicit: add to [workspace]:\n"
        "          root = '/path/to/workspace'\n"
        "        (or per-component: catalog_path, data_dir, runs_dir)"
    )
