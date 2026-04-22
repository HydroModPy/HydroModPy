"""Shared solver-engine enumeration used by HydroModPy configuration."""

from __future__ import annotations

from enum import StrEnum


class SolverEngine(StrEnum):
    """Supported groundwater solver backends."""

    MODFLOW_NWT = "modflownwt"
    MODFLOW6 = "modflow6"
    BOUSSINESQ = "boussinesq"
