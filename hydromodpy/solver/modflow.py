"""Backward-compatible shim for MODFLOW imports."""

from hydromodpy.solver.modflow_nwt import Modflow, ModflowConfig

__all__ = ["Modflow", "ModflowConfig"]
