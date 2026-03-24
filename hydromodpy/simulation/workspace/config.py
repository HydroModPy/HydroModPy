from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.config.param_level import ParamLevel


class WorkspaceConfig(BaseModel):
    """
    Workspace configuration for project-based workspace structure.

    The workspace layout is convention-based::

        workspace_root/
            catalog.db
            data/
            projects/
                <project>/          <- project_root
                    results_stable/
                    results_simulations/
                    results_calibration/
    """

    model_config = ConfigDict(extra="forbid")

    project_root: Annotated[Path, ParamLevel("user")] = Field(
        description=(
            "Path to the project directory. "
            "Auto-derived from TOML location when absent."
        ),
    )

    output_root: Annotated[Path | None, ParamLevel("user")] = Field(
        default=None,
        description=(
            "Root directory for all outputs (results_stable/, results_simulations/, "
            "results_calibration/). Defaults to project_root when not set. "
            "Use this to redirect heavy outputs to a separate disk."
        ),
    )

    workspace_root: Annotated[Path | None, ParamLevel("dev")] = Field(
        default=None,
        description=(
            "Root of the workspace containing data/ and projects/. "
            "Auto-discovered by walking up from project_root."
        ),
    )

    @model_validator(mode="after")
    def _resolve_workspace_root(self) -> "WorkspaceConfig":
        if self.workspace_root is None:
            discovered = self.discover_workspace_root(self.project_root)
            if discovered is not None:
                self.workspace_root = discovered
        return self

    @staticmethod
    def discover_workspace_root(project_root: Path) -> Path | None:
        """Walk up from project_root to find the workspace root.

        Detection heuristics (in order):
        1. project_root sits directly under a ``projects/`` directory,
        2. an ancestor contains ``catalog.db`` or a ``data/`` directory.
        """
        resolved = Path(project_root).resolve()
        if resolved.parent.name == "projects":
            return resolved.parent.parent
        for parent in resolved.parents:
            if (parent / "catalog.db").exists() or (parent / "data").is_dir():
                return parent
        return None

    # -- Derived properties (same names, new derivation) -------------------

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
    def stable_folder(self) -> Path:
        """Path to the stable/preprocessing results directory."""
        return self._effective_output_root / "results_stable"

    @property
    def simulations_folder(self) -> Path:
        """Path to the simulations results directory."""
        return self._effective_output_root / "results_simulations"

    @property
    def calibration_folder(self) -> Path:
        """Path to the calibration results directory."""
        return self._effective_output_root / "results_calibration"

    @property
    def data_path(self) -> Path | None:
        """Path to the shared data folder, or None if no workspace root."""
        if self.workspace_root is not None:
            return self.workspace_root / "data"
        return None

    @property
    def catalog_path(self) -> Path | None:
        """Path to the shared catalog database, or None if no workspace root."""
        if self.workspace_root is not None:
            return self.workspace_root / "catalog.db"
        return None
