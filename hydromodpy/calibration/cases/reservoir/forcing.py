# -*- coding: utf-8 -*-
"""
Reservoir forcing compatibility layer.

The forcing implementation is now centralized in:
`hydromodpy.calibration.cases.utils.forcing`.

This module re-exports the same public helpers so existing imports remain
valid while reservoir and groundwater cases share one implementation.
"""

from __future__ import annotations

from hydromodpy.calibration.cases.utils.forcing import (
    build_hydrological_year_dates,
    enforce_annual_precipitation_total,
    generate_daily_precipitation,
    make_piecewise_constant_daily_qin,
    precipitation_to_inflow,
)

__all__ = (
    "build_hydrological_year_dates",
    "enforce_annual_precipitation_total",
    "generate_daily_precipitation",
    "make_piecewise_constant_daily_qin",
    "precipitation_to_inflow",
)


