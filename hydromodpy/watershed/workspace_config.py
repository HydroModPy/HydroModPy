from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hydromodpy.config.param_level import ParamLevel


class WorkspaceConfig(BaseModel):
    """
    Workspace configuration for watershed project structure.

    This model validates and stores the core paths and names used to organize
    model outputs and intermediate results.
    """

    model_config = ConfigDict(extra="forbid")

    catch_name: Annotated[str, ParamLevel("user")] = Field(
        description="Name of the watershed/catchment (used as folder name).",
        min_length=1,
    )

    @field_validator("catch_name", mode="before")
    @classmethod
    def _validate_catch_name(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("catch_name cannot be empty or whitespace-only")
        return text
    out_dir_path: Annotated[Path, ParamLevel("user")] = Field(
        description="Root output directory where all results will be stored."
    )
    data_path: Annotated[Path, ParamLevel("user")] = Field(
        description="Path to the input data folder (observations, climate, GIS layers, etc.)."
    )

    @property
    def catch_folder(self) -> Path:
        """Path to the main catchment folder."""
        return self.out_dir_path / self.catch_name

    @property
    def stable_folder(self) -> Path:
        """Path to the stable/preprocessing results directory."""
        return self.out_dir_path / self.catch_name / "results_stable"

    @property
    def simulations_folder(self) -> Path:
        """Path to the simulations results directory."""
        return self.out_dir_path / self.catch_name / "results_simulations"

    @property
    def calibration_folder(self) -> Path:
        """Path to the calibration results directory."""
        return self.out_dir_path / self.catch_name / "results_calibration"
