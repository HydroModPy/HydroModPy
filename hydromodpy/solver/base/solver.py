"""Internal convention for HydroModPy numerical model classes.

Concrete numerical model classes (Modflow, Modflow6, Modpath, Boussinesq)
inherit from :class:`Solver` to share the same ``pre_processing``,
``processing`` and ``post_processing`` hooks. This is **not** the public
solver-adapter contract: the adapter contract is the structural
:class:`SolverAdapter` Protocol declared in
:mod:`hydromodpy.solver.base.protocol`. ``Solver`` only standardises the
private lifecycle of the in-tree numerical model classes themselves.
"""

from abc import ABC, abstractmethod


class Solver(ABC):
    """Internal lifecycle convention for HydroModPy numerical model classes."""

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
