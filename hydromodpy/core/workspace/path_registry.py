"""Canonical workspace path registry shared by runtime components."""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

from hydromodpy.core.state.paths import (
    REPORTS_DIRNAME,
    run_scratch,
    scratch_dir_for,
    share_dir_for,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

_F = TypeVar("_F", bound=Callable[..., Any])


def in_run_scratch(
    root_of: Callable[..., Path],
    label_of: Callable[..., str],
    *,
    check: Callable[..., None] | None = None,
) -> Callable[[_F], _F]:
    """Run the decorated function inside its own run scratch (``core.state.paths.run_scratch``).

    ``root_of`` and ``label_of`` receive the call's arguments and return the
    project root and the name the scratch folder starts with. ``check``, when
    given, receives them first and raises to refuse the call before anything is
    written, so a refused call leaves nothing on disk.
    """

    def decorate(fn: _F) -> _F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if check is not None:
                check(*args, **kwargs)
            with run_scratch(root_of(*args, **kwargs), label_of(*args, **kwargs)):
                return fn(*args, **kwargs)

        return cast(_F, wrapper)

    return decorate


def project_root_of_config(config_path: Path, workspace: Path | str | None = None) -> Path:
    """Return the project root a TOML config runs in.

    ``workspace`` wins when given, then ``HMP_PROJECT_ROOT``, then the
    ``[workspace] project_root`` of the config and its ``base_config`` chain,
    relative to the config's folder, then that folder.
    """
    if workspace is not None:
        return Path(workspace).expanduser().resolve()
    env_root = os.environ.get("HMP_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    config_path = Path(config_path).expanduser().resolve()
    try:
        raw = load_toml_with_base_config(config_path)
    except (OSError, ValueError, TypeError):
        raw = {}
    declared = (raw.get("workspace") or {}).get("project_root")
    if declared:
        candidate = Path(str(declared)).expanduser()
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        return candidate.resolve()
    return config_path.parent


if TYPE_CHECKING:
    from hydromodpy.core.workspace.config import WorkspaceConfig


@dataclass(frozen=True)
class WorkspacePathRegistry:
    """Centralize shared data and project-local result paths."""

    project_root: Path
    root: Path
    catalog_path: Path
    data_dir: Path
    runs_dir: Path
    output_root: Path | None = None

    @classmethod
    def from_config(cls, config: WorkspaceConfig) -> WorkspacePathRegistry:
        """Build a registry from a fully resolved workspace config."""
        return cls(
            project_root=Path(config.project_root),
            root=Path(config.root),
            catalog_path=Path(config.catalog_path),
            data_dir=Path(config.data_dir),
            runs_dir=Path(config.runs_dir),
            output_root=Path(config.output_root) if config.output_root else None,
        )

    # -- Derived convenience names -----------------------------------------

    @property
    def _effective_output_root(self) -> Path:
        """Root for result directories: output_root if set, else project_root."""
        if self.output_root is not None:
            return self.output_root
        return self.project_root

    @property
    def catch_name(self) -> str:
        return self.project_root.name

    @property
    def solver_scratch_folder(self) -> Path:
        return scratch_dir_for(self._effective_output_root)

    def solver_scratch_run_folder(self, sim_id: str) -> Path:
        """Return the scratch folder for a specific solver run."""
        return self.solver_scratch_folder / sim_id

    @property
    def share_folder(self) -> Path:
        return share_dir_for(self._effective_output_root)

    @property
    def reports_folder(self) -> Path:
        return self.share_folder / REPORTS_DIRNAME

    @property
    def figures_folder(self) -> Path:
        """Figures that belong to the project, not to one run."""
        return self.share_folder / "figures"

    @property
    def data_path(self) -> Path:
        return self.data_dir

    def figures_subdir(self, *parts: str) -> Path:
        return self.figures_folder.joinpath(*parts)

    def manager_figure_folder(self, manager_type: str) -> Path:
        """Return canonical figure folder for one data-manager type."""
        token = str(manager_type).strip().lower()
        if not token:
            raise ValueError("manager_type cannot be empty")
        return self.figures_subdir(token)
