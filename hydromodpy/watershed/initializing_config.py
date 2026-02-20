from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field

from hydromodpy.watershed.geographic_config import ParamLevel


class InitializingConfig(BaseModel):
    """
    Initialization configuration for watershed project structure.

    This model validates and stores the core paths and names used to organize
    model outputs and intermediate results.
    """

    catch_name: Annotated[str, ParamLevel("user")] = Field(
        description="Name of the watershed/catchment (used as folder name)."
    )
    out_dir_path: Annotated[Path, ParamLevel("user")] = Field(
        description="Root output directory where all results will be stored."
    )
    data_path: Annotated[Path, ParamLevel("user")] = Field(
        description="Path to the input data folder (observations, climate, GIS layers, etc.)."
    )

    @property
    def catch_folder(self) -> Path:
        """
        Path to the main catchment folder.

        Returns
        -------
        Path
            The combined path of the root output directory and catchment name.
        """
        return self.out_dir_path / self.catch_name

    @property
    def stable_folder(self) -> Path:
        """
        Path to the folder where stable/preprocessing results are stored.

        Returns
        -------
        Path
            The absolute path to the stable results directory.
        """
        return self.out_dir_path / self.catch_name / "results_stable"

    @property
    def simulations_folder(self) -> Path:
        """
        Path to the folder where simulation outputs are stored.

        Returns
        -------
        Path
            The absolute path to the simulations directory.
        """
        return self.out_dir_path / self.catch_name / "results_simulations"

    @property
    def calibration_folder(self) -> Path:
        """
        Path to the folder where calibration results are stored.

        Returns
        -------
        Path
            The absolute path to the calibration results directory.
        """
        return self.out_dir_path / self.catch_name / "results_calibration"
