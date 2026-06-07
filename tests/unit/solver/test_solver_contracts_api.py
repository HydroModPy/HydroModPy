"""Compatibility checks for solver contract imports."""

from __future__ import annotations

import hydromodpy.solver as solver_root
from hydromodpy.solver.base import (
    SolverAdapter as BaseSolverAdapter,
)
from hydromodpy.solver.base import (
    SolverConfig as BaseSolverConfig,
)
from hydromodpy.solver.contracts import (
    SolverAdapter as ContractSolverAdapter,
)
from hydromodpy.solver.contracts import (
    SolverConfig as ContractSolverConfig,
)


def test_solver_contracts_module_reexports_base_symbols() -> None:
    assert ContractSolverAdapter is BaseSolverAdapter
    assert ContractSolverConfig is BaseSolverConfig


def test_solver_root_reexports_contract_symbols() -> None:
    assert solver_root.SolverAdapter is ContractSolverAdapter
    assert solver_root.SolverConfig is ContractSolverConfig
