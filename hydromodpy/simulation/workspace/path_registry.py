"""Canonical workspace path registry shared by runtime components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.simulation.workspace.config import WorkspaceConfig


@dataclass(frozen=True)
class WorkspacePathRegistry:
    """Centralize canonical input/output paths for one workspace."""

    catch_name: str
    out_dir_path: Path
    data_path: Path

    @classmethod
    def from_config(cls, config: "WorkspaceConfig") -> "WorkspacePathRegistry":
        """Build a registry from validated workspace config."""
        return cls(
            catch_name=config.catch_name,
            out_dir_path=Path(config.out_dir_path),
            data_path=Path(config.data_path),
        )

    @property
    def catch_folder(self) -> Path:
        return self.out_dir_path / self.catch_name

    @property
    def stable_folder(self) -> Path:
        return self.catch_folder / "results_stable"

    @property
    def simulations_folder(self) -> Path:
        return self.catch_folder / "results_simulations"

    @property
    def calibration_folder(self) -> Path:
        return self.catch_folder / "results_calibration"

    @property
    def add_data_folder(self) -> Path:
        return self.stable_folder / "add_data"

    @property
    def figures_folder(self) -> Path:
        return self.stable_folder / "_figures"

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
