"""Pedagogical entry points for the standalone Boussinesq backend.

Importing from this package gives access to the three public objects that matter
most to callers:

- :class:`Boussinesq`, the high-level solver driver;
- :class:`BoussinesqMesh`, the compact mesh view consumed by the solver;
- :class:`BoussinesqState`, the normalized in-memory flow state.

The detailed implementation is intentionally split across several modules:

- ``mesh.py``: geometry and material properties;
- ``assembly.py``: residual assembly;
- ``core/``, ``discretization/``, ``formulations/``, ``methods/`` and
  ``engines/``: explicit taxonomy for state, schemes, formulations and
  execution engines;
- ``local_runtime.py``, ``scipy_runtime.py``, ``scipy_sparse_runtime.py`` and
  ``petsc_runtime.py``: runtime implementations kept for compatibility;
- ``boussinesq.py``: orchestration around the HydroModPy launcher contract.
"""

from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

__all__ = ["Boussinesq", "BoussinesqMesh", "BoussinesqState"]
