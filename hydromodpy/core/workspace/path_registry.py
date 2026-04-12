"""Canonical workspace path registry shared by runtime components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

#: Preprocessing intermediates go under .solver_scratch/_preprocessing/.
#: These files are needed on disk by whitebox/rasterio during the pipeline,
#: then ingested into the project store and cleaned up.
LEGACY_STABLE_DIR = ".solver_scratch/_preprocessing"

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
    def solver_scratch_folder(self) -> Path:
        return self._effective_output_root / ".solver_scratch"

    def solver_scratch_run_folder(self, sim_id: str) -> Path:
        """Return the scratch folder for a specific solver run."""
        return self.solver_scratch_folder / sim_id

    @property
    def figures_folder(self) -> Path:
        return self._effective_output_root / "figures"

    @property
    def data_path(self) -> Path | None:
        if self.workspace_root is not None:
            return self.workspace_root / "data"
        return None

    @property
    def catalog_path(self) -> Path | None:
        if self.workspace_root is not None:
            return self.workspace_root / "catalog.duckdb"
        return None

    def figures_subdir(self, *parts: str) -> Path:
        return self.figures_folder.joinpath(*parts)

    def manager_figure_folder(self, manager_type: str) -> Path:
        """Return canonical figure folder for one data-manager type."""
        token = str(manager_type).strip().lower()
        if not token:
            raise ValueError("manager_type cannot be empty")
        return self.figures_subdir(token)
