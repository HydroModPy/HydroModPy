"""Shared negative-recharge to EVT routing for MODFLOW 6 and MODFLOW-NWT.

A negative net recharge (precipitation minus evapotranspiration) is a climatic
deficit. It is clipped out of RCH and routed to an EVT sink. On a steady spin-up
period the forcing must be the long-term time mean, so both the positive recharge
and the routed deficit carry the per-cell mean over all periods. Transient periods
keep their own positive/negative split. Keying on the steady flag (not kper == 0)
makes a transient first period keep its own split.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def route_negative_recharge_to_evt(
    rch_by_period: dict[int, np.ndarray],
    *,
    steady: Sequence[bool],
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """Split per-period recharge into clipped RCH (>=0) and routed EVT deficit (>=0).

    Returns ``(clipped_rch, evt_deficit)``. Steady periods carry the per-cell time
    mean (over all periods); transient periods keep their own split.
    """
    periods = sorted(int(k) for k in rch_by_period)
    arrays = {k: np.asarray(rch_by_period[k], dtype=float) for k in periods}
    positive = {k: np.maximum(arrays[k], 0.0) for k in periods}
    deficit = {k: np.abs(np.minimum(arrays[k], 0.0)) for k in periods}
    mean_positive = np.mean([positive[k] for k in periods], axis=0)
    mean_deficit = np.mean([deficit[k] for k in periods], axis=0)

    clipped_rch: dict[int, np.ndarray] = {}
    evt_deficit: dict[int, np.ndarray] = {}
    for k in periods:
        is_steady = bool(steady[k]) if k < len(steady) else False
        if is_steady:
            clipped_rch[k] = np.array(mean_positive, dtype=float, copy=True)
            evt_deficit[k] = np.array(mean_deficit, dtype=float, copy=True)
        else:
            clipped_rch[k] = positive[k].astype(float, copy=False)
            evt_deficit[k] = deficit[k].astype(float, copy=False)
    return clipped_rch, evt_deficit


__all__ = ["route_negative_recharge_to_evt"]
