"""Pedagogical entry points for the standalone Boussinesq backend.

Importing from this package gives access to the three public objects that matter
most to callers:

- :class:`Boussinesq`, the high-level solver driver;
- :class:`BoussinesqMesh`, the compact mesh view consumed by the solver;
- :class:`BoussinesqState`, the normalized in-memory flow state.

The detailed implementation is intentionally split across several modules:

- ``mesh.py``: geometry and material properties;
- ``assembly/``: residual assembly and boundary-flux reconstruction;
- ``jacobian/``: finite-difference and semianalytic Jacobian builders;
- ``drivers/``: steady/transient orchestration helpers;
- ``core/``, ``discretization/``, ``formulations/``, ``methods/`` and
  ``engines/``: explicit taxonomy for state, schemes, formulations and
  execution engines;
- ``runtimes/``: shared runtime utilities and supported execution backends;
- ``boussinesq.py``: orchestration around the HydroModPy launcher contract.
"""

from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

__all__ = ["Boussinesq", "BoussinesqMesh", "BoussinesqState"]
