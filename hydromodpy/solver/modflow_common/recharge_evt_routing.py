"""Shared negative-recharge to EVT routing for MODFLOW 6 and MODFLOW-NWT.

A negative net recharge (precipitation minus evapotranspiration) is a climatic
deficit. It is clipped out of RCH and routed to an EVT sink. A transient period
keeps its own split. A steady period takes, on each part, the rate
``first_clim`` states, so its net rate is the one ``first_clim`` states
(:mod:`hydromodpy.physics.forcing.steady_periods`). The routing keys on the
steady flag, not on ``kper == 0``.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from hydromodpy.physics.forcing.steady_periods import split_net_recharge


def route_negative_recharge_to_evt(
    rch_by_period: dict[int, np.ndarray],
    *,
    steady: Sequence[bool],
    first_clim: object = "mean",
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """Split per-period recharge into clipped RCH (>=0) and routed EVT deficit (>=0).

    Returns ``(clipped_rch, evt_deficit)``. Transient periods keep their own
    split; steady periods follow ``first_clim`` on each part.
    """
    return split_net_recharge(rch_by_period, steady=steady, first_clim=first_clim)


__all__ = ["route_negative_recharge_to_evt"]
