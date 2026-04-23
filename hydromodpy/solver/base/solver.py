"""Abstract base class for HydroModPy solvers (Modflow, Modpath, Mt3dms).

Defines the common interface that every concrete solver must implement.
"""

from abc import ABC, abstractmethod


class Solver(ABC):
    """Abstract base class for HydroModPy solvers."""

    @abstractmethod
    def pre_processing(self) -> None:
        """Prepare input files and data structures before the solver run."""

    @abstractmethod
    def processing(self, write_model: bool = True, run_model: bool = False, **kwargs) -> bool:
        """Write model files and optionally execute the solver.

        Parameters
        ----------
        write_model:
            Write the solver input files.
        run_model:
            Execute the solver binary.

        Returns
        -------
        bool
            Whether the simulation completed successfully.
        """

    @abstractmethod
    def post_processing(self, *args, **kwargs) -> None:
        """Analyse and export results (figures, rasters, etc.)."""

    def validate_config(self) -> None:  # noqa: B027 - intentional optional hook
        """Validate solver-specific configuration before execution.

        Subclasses should override this to check parameter ranges, file
        existence, etc. The default implementation is a no-op.
        """

    def get_results(self) -> dict:
        """Return a summary of solver outputs.

        Subclasses should override this to return paths to output files,
        convergence metrics, etc. The default returns an empty dict.
        """
        return {}

    def cleanup(self) -> None:  # noqa: B027 - intentional optional hook
        """Release resources and remove temporary files.

        Subclasses should override this when the solver creates large
        scratch files that should be removed after post-processing.
        """
