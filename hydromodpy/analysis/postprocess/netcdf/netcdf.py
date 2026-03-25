# -*- coding: utf-8 -*-
"""Backward-compatible NetCDF postprocess entry point."""

from hydromodpy.analysis.postprocess.netcdf.transport_netcdf import TransportNetcdfPostprocess


class Netcdf(TransportNetcdfPostprocess):
    """Canonical NetCDF postprocess class (flow + optional transport outputs)."""


__all__ = [
    "Netcdf",
]
