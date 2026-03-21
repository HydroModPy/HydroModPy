"""Minimal local Boussinesq solver backend.

The first implementation slice focuses on:

- consuming one gmsh ``CatchmentMeshBundle``,
- building one solver-owned mesh view,
- initializing the head state from ``Flow`` initial conditions.

Time integration and the full nonlinear residual come later on top of the same
runtime objects.
"""

from hydromodpy.solver.boussinesq.boussinesq import Boussinesq, BoussinesqState
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

__all__ = ["Boussinesq", "BoussinesqMesh", "BoussinesqState"]
