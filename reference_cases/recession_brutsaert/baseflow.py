"""Brutsaert recession reference case utilities."""

import numpy as np


def _resolve_area_length(A, L):
    """Resolve missing area/length using L = 1.4 * sqrt(A)."""
    if A is None and L is None:
        raise ValueError("Either A or L must be provided")

    if L is None:
        L = 1.4 * np.sqrt(A)

    if A is None:
        A = (L / 1.4) ** 2

    return A, L


def compute_characteristic_time(
    Q0,
    K,
    Sy,
    solution="boussinesq",
    b=None,
    A=None,
    L=None,
    ag=0.7,
    p=0.346,
):
    """
    Compute characteristic groundwater recession time scale.

    Parameters
    ----------
    Q0 : float
        Initial discharge [m^3/s]
    K : float
        Hydraulic conductivity [m/s]
    Sy : float
        Specific yield [-]
    solution : str
        "exponential" or "boussinesq"
    b : float
        Aquifer thickness [m] (required for exponential)
    A : float
        Watershed area [m^2]
    L : float
        Channel length [m]
    ag : float
        Active drainage fraction [-]
    p : float
        Linearization constant [-]

    Returns
    -------
    float
        Characteristic time [s]
    """
    A, L = _resolve_area_length(A, L)

    if solution == "exponential":
        if b is None:
            raise ValueError("Aquifer thickness b required for exponential solution")

        a = np.pi**2 * K * p * b * L**2 / (Sy * (ag * A) ** 2)
        tc = 1.0 / a

    elif solution == "boussinesq":
        beta = (4.8038 / 2.0) * np.sqrt(K) * L / (Sy * (ag * A) ** 1.5)
        tc = 1.0 / (beta * np.sqrt(Q0))

    else:
        raise ValueError("invalid solution")

    return tc


def simulate_baseflow(
    t,
    Q0,
    K,
    Sy,
    solution="boussinesq",
    b=None,
    A=None,
    L=None,
    ag=0.7,
    p=0.346,
):
    """
    Compute discharge time series Q(t).

    Parameters are identical to `compute_characteristic_time`,
    with `t` being time in seconds.
    """
    t = np.asarray(t)
    A, L = _resolve_area_length(A, L)

    if solution == "exponential":
        if b is None:
            raise ValueError("b required")

        Q = Q0 * np.exp(-(np.pi**2 * K * p * b * L**2) / (Sy * (ag * A) ** 2) * t)

    elif solution == "boussinesq":
        Q = (Q0 ** (-0.5) + (4.8038 / 2.0) * np.sqrt(K) * L / (Sy * (ag * A) ** 1.5) * t) ** (-2)

    else:
        raise ValueError("invalid solution")

    return Q


def generate_baseflow_profile(
    Q0,
    K,
    Sy,
    solution="boussinesq",
    b=None,
    A=None,
    L=None,
    ag=0.7,
    p=0.346,
    n_points=500,
    log_spacing=True,
    t_max_days=None,
):
    """
    Generate full discharge profile with automatic time scaling.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, float]
        (t_seconds, t_days, Q, tc_seconds)
    """
    tc = compute_characteristic_time(
        Q0,
        K,
        Sy,
        solution=solution,
        b=b,
        A=A,
        L=L,
        ag=ag,
        p=p,
    )

    if t_max_days is None:
        t_max_days = 5.0 * tc / 86400.0

    if log_spacing:
        t_days = np.logspace(-3, np.log10(t_max_days), n_points)
    else:
        t_days = np.linspace(0, t_max_days, n_points)

    t = t_days * 86400.0

    Q = simulate_baseflow(
        t,
        Q0,
        K,
        Sy,
        solution=solution,
        b=b,
        A=A,
        L=L,
        ag=ag,
        p=p,
    )

    return t, t_days, Q, tc
