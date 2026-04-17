"""Compatibility exports for generic solver contracts.

Concrete solver implementations live in subpackages such as
``hydromodpy.solver.modflow6``, ``hydromodpy.solver.modflow_nwt`` and
``hydromodpy.solver.boussinesq``.

The generic ``Solver`` / ``SolverConfig`` / ``SolverEngine`` exports remain
available from this root module for backward compatibility, but internal code
should import them from ``hydromodpy.solver.contracts`` instead.
"""

from __future__ import annotations

import warnings

__all__ = ["Solver", "SolverConfig", "SolverEngine"]


def __getattr__(name: str):
    if name in __all__:
        from hydromodpy.solver import contracts

        warnings.warn(
            f"'hydromodpy.solver.{name}' is a backward-compatibility export. "
            f"Import it from 'hydromodpy.solver.contracts' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(contracts, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
