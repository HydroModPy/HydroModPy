"""Shared solver-engine enumeration used by HydroModPy configuration."""

from __future__ import annotations

from enum import Enum


class SolverEngine(str, Enum):
    """Supported groundwater solver backends."""

    MODFLOW_NWT = "nwt"
    MODFLOW6 = "mf6"
