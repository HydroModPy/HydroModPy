# -*- coding: utf-8 -*-
"""
Reservoir equations for a linear storage-outflow model.

This module contains only model equations and simulation logic.
Plotting and demonstration scenarios are intentionally kept out of this file.
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp


class ReservoirModel:
    """
    Linear reservoir model with finite storage capacity (lame d'eau).

    Model equations
    ---------------
    Qout = k * S
    dS/dt = Qin(t) - Qout

    with physical clipping:
    - 0 <= S <= C
    - no negative storage variation at S=0
    - no positive storage variation at S=C
    """

    def __init__(self, capacity: float, k: float):
        """
        Parameters
        ----------
        capacity : float
            Maximum storage C [mm].
        k : float
            Linear outflow coefficient in Qout = k * S [1/time].
        """
        capacity = float(capacity)
        k = float(k)
        if capacity <= 0.0:
            raise ValueError("capacity must be > 0")
        if k < 0.0:
            raise ValueError("k must be >= 0")

        self.C = capacity
        self.k = k

    def qout(self, storage: float) -> float:
        """Return outflow for a given storage S [mm]."""
        return self.k * float(storage)

    def dynamics(self, t, state, qin_func):
        """
        ODE right-hand side for solve_ivp.

        Parameters
        ----------
        t : float
            Current time.
        state : sequence
            Current state vector, expected as [S] with S in [mm].
        qin_func : callable
            Inflow function Qin(t).
        """
        storage = float(np.clip(state[0], 0.0, self.C))
        qin = float(qin_func(t))
        qout = self.qout(storage)

        dstorage_dt = qin - qout

        # Physical saturation guards.
        if storage <= 0.0 and dstorage_dt < 0.0:
            dstorage_dt = 0.0
        if storage >= self.C and dstorage_dt > 0.0:
            dstorage_dt = 0.0

        return [dstorage_dt]

    def simulate(self, qin_func, s0, t_span, t_eval):
        """
        Simulate reservoir dynamics over a time window.

        Parameters
        ----------
        qin_func : callable
            Inflow function Qin(t).
        s0 : float
            Initial storage [mm].
        t_span : tuple(float, float)
            Time interval (t0, tf).
        t_eval : array-like
            Times where the solution is sampled.

        Returns
        -------
        tuple(np.ndarray, np.ndarray, np.ndarray)
            (time, storage, qout) with storage in [mm] and flow in [mm/time].
        """
        s0 = float(s0)
        t_eval = np.asarray(t_eval, dtype=float)
        if t_eval.ndim != 1 or t_eval.size == 0:
            raise ValueError("t_eval must be a non-empty 1D array")

        solution = solve_ivp(
            self.dynamics,
            t_span,
            [s0],
            t_eval=t_eval,
            args=(qin_func,),
            method="RK45",
        )

        storage = np.clip(solution.y[0], 0.0, self.C)
        qout = self.k * storage
        return solution.t, storage, qout
