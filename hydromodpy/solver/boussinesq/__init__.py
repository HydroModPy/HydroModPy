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

from __future__ import annotations

from importlib import import_module

__all__ = ["Boussinesq", "BoussinesqMesh", "BoussinesqState"]

_LAZY_IMPORTS = {
    "Boussinesq": "hydromodpy.solver.boussinesq.boussinesq:Boussinesq",
    "BoussinesqMesh": "hydromodpy.solver.boussinesq.mesh:BoussinesqMesh",
    "BoussinesqState": "hydromodpy.solver.boussinesq.core.state:BoussinesqState",
}


def __getattr__(name: str):
    try:
        target = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module_path, attr_name = target.split(":", 1)
    module = import_module(module_path)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
