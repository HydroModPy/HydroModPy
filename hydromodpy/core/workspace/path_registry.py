"""Canonical workspace path registry shared by runtime components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.state.paths import (
    INTERNAL_DIRNAME,
    REPORTS_DIRNAME,
    scratch_dir_for,
    share_dir_for,
)

#: Preprocessing intermediates go under .hmp/scratch/_preprocessing/.
#: These files are needed on disk by whitebox/rasterio during the pipeline,
#: then ingested into the project store and cleaned up.
PREPROCESSING_DIR = f"{INTERNAL_DIRNAME}/scratch/_preprocessing"

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
