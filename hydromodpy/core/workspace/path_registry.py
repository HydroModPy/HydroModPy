"""Canonical workspace path registry shared by runtime components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.core.workspace.config import WorkspaceConfig


@dataclass(frozen=True)
class WorkspacePathRegistry:
    """Centralize canonical input/output paths for one workspace."""

    project_root: Path
    output_root: Path | None = None
    workspace_root: Path | None = None

    @classmethod
    def from_config(cls, config: "WorkspaceConfig") -> "WorkspacePathRegistry":
        """Build a registry from validated workspace config."""
        return cls(
            project_root=Path(config.project_root),
            output_root=Path(config.output_root) if config.output_root else None,
            workspace_root=Path(config.workspace_root) if config.workspace_root else None,
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
    def stable_folder(self) -> Path:
        return self._effective_output_root / "results_stable"

    @property
    def simulations_folder(self) -> Path:
        return self._effective_output_root / "results_simulations"

    @property
    def calibration_folder(self) -> Path:
        return self._effective_output_root / "results_calibration"

    @property
    def add_data_folder(self) -> Path:
        return self.stable_folder / "add_data"

    @property
    def figures_folder(self) -> Path:
        return self.stable_folder / "_figures"

    @property
    def data_path(self) -> Path | None:
        if self.workspace_root is not None:
            return self.workspace_root / "data"
        return None

    @property
    def catalog_path(self) -> Path | None:
        if self.workspace_root is not None:
            return self.workspace_root / "catalog.db"
        return None

    def run_folder(self, run_id: str) -> Path:
        """Return the output folder for a specific run."""
        return self.simulations_folder / run_id

    def stable_subdir(self, *parts: str) -> Path:
        return self.stable_folder.joinpath(*parts)

    def figures_subdir(self, *parts: str) -> Path:
        return self.figures_folder.joinpath(*parts)

    def manager_stable_folder(self, manager_type: str) -> Path:
        """Return canonical stable output folder for one data-manager type."""
        token = str(manager_type).strip().lower()
        if not token:
            raise ValueError("manager_type cannot be empty")
        return self.stable_subdir(token)

    def manager_figure_folder(self, manager_type: str) -> Path:
        """Return canonical figure folder for one data-manager type."""
        token = str(manager_type).strip().lower()
        if not token:
            raise ValueError("manager_type cannot be empty")
        return self.figures_subdir(token)
