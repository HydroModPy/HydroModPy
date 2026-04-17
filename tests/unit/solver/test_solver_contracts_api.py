"""Compatibility checks for solver contract imports."""

from __future__ import annotations

import warnings

import hydromodpy.solver as solver_root
from hydromodpy.solver.contracts import (
    Solver as ContractSolver,
    SolverConfig as ContractSolverConfig,
    SolverEngine as ContractSolverEngine,
)
from hydromodpy.solver.prototype import (
    Solver as PrototypeSolver,
    SolverConfig as PrototypeSolverConfig,
    SolverEngine as PrototypeSolverEngine,
)


def test_solver_contracts_module_reexports_prototype_symbols() -> None:
    assert ContractSolver is PrototypeSolver
    assert ContractSolverConfig is PrototypeSolverConfig
    assert ContractSolverEngine is PrototypeSolverEngine


def test_solver_root_reexports_contract_symbols_for_compatibility() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        solver = solver_root.Solver
        solver_config = solver_root.SolverConfig
        solver_engine = solver_root.SolverEngine

    assert solver is ContractSolver
    assert solver_config is ContractSolverConfig
    assert solver_engine is ContractSolverEngine
    assert len(caught) == 3
    for warning in caught:
        assert issubclass(warning.category, DeprecationWarning)
        assert "hydromodpy.solver.contracts" in str(warning.message)
