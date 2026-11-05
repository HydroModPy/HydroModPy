"""Canonical workspace path registry shared by runtime components."""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

from hydromodpy.core.state.scratch import run_scratch, scratch_dir_for

_F = TypeVar("_F", bound=Callable[..., Any])


def in_run_scratch(
    root_of: Callable[..., Path],
    label_of: Callable[..., str],
    *,
    check: Callable[..., None] | None = None,
) -> Callable[[_F], _F]:
    """Run the decorated function inside its own run scratch (``core.state.scratch.run_scratch``).

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


if TYPE_CHECKING:
    from hydromodpy.core.workspace.config import WorkspaceConfig


@dataclass(frozen=True)
class WorkspacePathRegistry:
    """Centralize the shared data paths and the project-local index and runs paths.

    A result is written in the directory of what produced it (a run, a
    session, the summary), never in a project-wide output folder: this
    registry names no figures, reports or exports folder.
    """

    project_root: Path
    root: Path
    catalog_path: Path
    data_dir: Path
    runs_dir: Path

    @classmethod
    def from_config(cls, config: WorkspaceConfig) -> WorkspacePathRegistry:
        """Build a registry from a fully resolved workspace config."""
        return cls(
            project_root=Path(config.project_root),
            root=Path(config.root),
            catalog_path=Path(config.catalog_path),
            data_dir=Path(config.data_dir),
            runs_dir=Path(config.runs_dir),
        )

    @property
    def solver_scratch_folder(self) -> Path:
        return scratch_dir_for(self.project_root)

    def solver_scratch_run_folder(self, sim_id: str) -> Path:
        """Return the scratch folder for a specific solver run."""
        return self.solver_scratch_folder / sim_id

    @property
    def data_path(self) -> Path:
        return self.data_dir
