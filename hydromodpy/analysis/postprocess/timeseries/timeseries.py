# -*- coding: utf-8 -*-
"""Backward-compatible timeseries entry point.

Prefer explicit classes:
- ``FlowTimeseriesPostprocess`` for flow-only exports,
- ``TransportTimeseriesPostprocess`` for flow+transport exports.
"""

from __future__ import annotations

from hydromodpy.analysis.postprocess.timeseries.transport_timeseries import (
    TransportTimeseriesPostprocess,
)


class Timeseries(TransportTimeseriesPostprocess):
    """Legacy class kept for compatibility.

    This class now inherits the transport-capable exporter, which also covers
    flow-only runs when transport arguments are left unset.
    """


__all__ = [
    "Timeseries",
]
