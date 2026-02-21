# -*- coding: utf-8 -*-
"""
Two-reservoir linear hydrological model with precipitation split.

Model equations
---------------
Parameters: (a, Kq, Ks)

    dSq/dt = a * P(t) - Sq / Kq
    dSs/dt = (1 - a) * P(t) - Ss / Ks

    Qq = Sq / Kq
    Qs = Ss / Ks
    Q  = Qq + Qs

This formulation is intentionally minimal:
- only 3 parameters,
- no explicit losses,
- no maximum storage bounds.
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp


MODEL_NAME = "two_reservoir"
MODEL_DISPLAY_NAME = "two-reservoir"
PARAMETER_ORDER = ("a", "Kq", "Ks")


def _require_float(config_section, key):
    """Read one required float key from chronicle config."""
    if key not in config_section:
        raise KeyError(f"Missing required chronicle key: {key}")
    return float(config_section[key])


def parse_chronicle_parameters(chronicle_cfg):
    """
    Parse two-reservoir true parameters and initial state from chronicle config.
    """
    true_params = {
        "a": _require_float(chronicle_cfg, "a_true"),
        "Kq": _require_float(chronicle_cfg, "kq_days_true"),
        "Ks": _require_float(chronicle_cfg, "ks_days_true"),
    }
    initial_state = {
        "sq0": float(chronicle_cfg.get("sq0_mm", 0.0)),
        "ss0": float(chronicle_cfg.get("ss0_mm", 0.0)),
    }
    return true_params, initial_state


class TwoReservoirModel:
    """
    Two linear reservoirs in parallel fed by precipitation split.

    Parameters
    ----------
    a : float
        Fraction of precipitation routed to the quick reservoir (0 <= a <= 1).
    kq : float
        Quick reservoir characteristic time Kq [time], must be > 0.
    ks : float
        Slow reservoir characteristic time Ks [time], must be > 0.
    """

    def __init__(self, a: float, kq: float, ks: float):
        a = float(a)
        kq = float(kq)
        ks = float(ks)

        if not (0.0 <= a <= 1.0):
            raise ValueError("a must be in [0, 1]")
        if kq <= 0.0:
            raise ValueError("kq must be > 0")
        if ks <= 0.0:
            raise ValueError("ks must be > 0")

        self.a = a
        self.Kq = kq
        self.Ks = ks

    def q_quick(self, sq: float) -> float:
        """Return quick-flow component Qq [mm/time]."""
        return float(sq) / self.Kq

    def q_slow(self, ss: float) -> float:
        """Return slow-flow component Qs [mm/time]."""
        return float(ss) / self.Ks

    def dynamics(self, t, state, precip_func):
        """
        ODE right-hand side for solve_ivp.

        Parameters
        ----------
        t : float
            Current time.
        state : sequence
            Current state [Sq, Ss] in [mm].
        precip_func : callable
            Precipitation forcing P(t) [mm/time].
        """
        sq = max(float(state[0]), 0.0)
        ss = max(float(state[1]), 0.0)
        precip = max(float(precip_func(t)), 0.0)

        dsq_dt = self.a * precip - self.q_quick(sq)
        dss_dt = (1.0 - self.a) * precip - self.q_slow(ss)
        return [dsq_dt, dss_dt]

    def simulate(self, precip_func, sq0, ss0, t_span, t_eval):
        """
        Simulate two-reservoir dynamics.

        Parameters
        ----------
        precip_func : callable
            Forcing P(t) [mm/time].
        sq0 : float
            Initial quick storage [mm].
        ss0 : float
            Initial slow storage [mm].
        t_span : tuple(float, float)
            Time interval (t0, tf).
        t_eval : array-like
            Times where the solution is sampled.

        Returns
        -------
        tuple(np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray)
            (time, sq, ss, qq, qs, q_total) with:
            - sq, ss in [mm]
            - qq, qs, q_total in [mm/time]
        """
        sq0 = float(sq0)
        ss0 = float(ss0)
        if sq0 < 0.0 or ss0 < 0.0:
            raise ValueError("Initial storages sq0 and ss0 must be >= 0")

        t_eval = np.asarray(t_eval, dtype=float)
        if t_eval.ndim != 1 or t_eval.size == 0:
            raise ValueError("t_eval must be a non-empty 1D array")

        solution = solve_ivp(
            self.dynamics,
            t_span,
            [sq0, ss0],
            t_eval=t_eval,
            args=(precip_func,),
            method="RK45",
        )

        sq = np.maximum(solution.y[0], 0.0)
        ss = np.maximum(solution.y[1], 0.0)
        qq = sq / self.Kq
        qs = ss / self.Ks
        q_total = qq + qs
        return solution.t, sq, ss, qq, qs, q_total


def simulate_outflow(params, initial_state, forcing_func, t_span, t_eval):
    """
    Simulate two-reservoir total outflow from parameters and forcing callable.

    Parameters
    ----------
    params : dict
        Must provide `a`, `Kq`, `Ks`.
    initial_state : dict
        Must provide `sq0` and `ss0`.
    forcing_func : callable
        P(t) forcing [mm/time].
    t_span : tuple(float, float)
        Integration time interval.
    t_eval : array-like
        Sampling times.

    Returns
    -------
    dict
        `{"qout": q_total, "sq": sq, "ss": ss, "storage": sq + ss}`.
    """
    params_all = {str(k): float(v) for k, v in params.items()}
    missing = [name for name in PARAMETER_ORDER if name not in params_all]
    if missing:
        raise ValueError(f"Missing two-reservoir parameter(s): {missing}")

    state = {str(k): float(v) for k, v in initial_state.items()}
    if "sq0" not in state or "ss0" not in state:
        raise ValueError("Missing initial state keys 'sq0'/'ss0' for two_reservoir")

    model = TwoReservoirModel(
        a=float(params_all["a"]),
        kq=float(params_all["Kq"]),
        ks=float(params_all["Ks"]),
    )
    _, sq, ss, _, _, q_total = model.simulate(
        precip_func=forcing_func,
        sq0=float(state["sq0"]),
        ss0=float(state["ss0"]),
        t_span=t_span,
        t_eval=t_eval,
    )
    return {
        "qout": q_total,
        "sq": sq,
        "ss": ss,
        "storage": sq + ss,
    }
