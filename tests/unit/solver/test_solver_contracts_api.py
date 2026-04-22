"""Compatibility checks for solver contract imports."""

from __future__ import annotations

import hydromodpy.solver as solver_root
from hydromodpy.solver.base import (
    Solver as BaseSolver,
)
from hydromodpy.solver.base import (
    SolverConfig as BaseSolverConfig,
)
from hydromodpy.solver.base import (
    SolverEngine as BaseSolverEngine,
)
from hydromodpy.solver.contracts import (
    Solver as ContractSolver,
)
from hydromodpy.solver.contracts import (
    SolverConfig as ContractSolverConfig,
)
from hydromodpy.solver.contracts import (
    SolverEngine as ContractSolverEngine,
)


def test_solver_contracts_module_reexports_base_symbols() -> None:
    assert ContractSolver is BaseSolver
    assert ContractSolverConfig is BaseSolverConfig
    assert ContractSolverEngine is BaseSolverEngine


def test_solver_root_reexports_contract_symbols() -> None:
    assert solver_root.Solver is ContractSolver
    assert solver_root.SolverConfig is ContractSolverConfig
    assert solver_root.SolverEngine is ContractSolverEngine
