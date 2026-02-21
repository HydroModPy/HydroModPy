"""
Brutsaert recession reference-case utilities.

This module provides:
- analytical recession equations (exponential and Boussinesq forms),
- characteristic-time computation helpers,
- profile generation on adaptive time grids,
- synthetic proportional Gaussian noise for testing/calibration workflows.
"""

import numpy as np


def _resolve_area_length(A, L):
    """
    Resolve watershed area/length pair using a geometric scaling relation.

    Parameters
    ----------
    A : float or None
        Watershed area [m^2].
    L : float or None
        Characteristic channel length [m].

    Returns
    -------
    tuple[float, float]
        `(A, L)` where both values are defined.

    Notes
    -----
    Uses:
        L = 1.4 * sqrt(A)
    if one variable is missing. If both are missing, geometry is undefined.
    """
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
        Initial discharge [m^3/s].
    K : float
        Hydraulic conductivity [m/s].
    Sy : float
        Specific yield [-].
    solution : str
        Analytical solution type: `"exponential"` or `"boussinesq"`.
    b : float or None
        Aquifer thickness [m], required for exponential solution.
    A : float or None
        Watershed area [m^2].
    L : float or None
        Channel length [m].
    ag : float
        Active drainage fraction [-].
    p : float
        Linearization constant [-].

    Returns
    -------
    float
        Characteristic time `tc` [s].

    Notes
    -----
    - Exponential form: `tc = 1 / a`.
    - Boussinesq form: `tc = 1 / (beta * sqrt(Q0))`.
    """
    # Ensure geometric descriptors are complete before using formulas.
    A, L = _resolve_area_length(A, L)

    if solution == "exponential":
        if b is None:
            raise ValueError("Aquifer thickness b required for exponential solution")

        # Linear recession rate coefficient for Q(t) = Q0 * exp(-a t).
        a = np.pi**2 * K * p * b * L**2 / (Sy * (ag * A) ** 2)
        tc = 1.0 / a

    elif solution == "boussinesq":
        # Nonlinear recession coefficient in Q(t) = [Q0^(-1/2) + beta t]^(-2).
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
    Compute analytical baseflow discharge time series `Q(t)`.

    Parameters
    ----------
    t : array-like
        Time values [s]. Scalar or vector-like.
    Q0 : float
        Initial discharge [m^3/s].
    K : float
        Hydraulic conductivity [m/s].
    Sy : float
        Specific yield [-].
    solution : str
        Analytical solution type: `"exponential"` or `"boussinesq"`.
    b : float or None
        Aquifer thickness [m], required for exponential solution.
    A : float or None
        Watershed area [m^2].
    L : float or None
        Channel length [m].
    ag : float
        Active drainage fraction [-].
    p : float
        Linearization constant [-].

    Returns
    -------
    np.ndarray
        Simulated discharge values [m^3/s], vectorized over `t`.
    """
    # Convert once so all subsequent operations are vectorized.
    t = np.asarray(t)
    A, L = _resolve_area_length(A, L)

    if solution == "exponential":
        if b is None:
            raise ValueError("b required")

        # Q(t) = Q0 * exp(-a t)
        Q = Q0 * np.exp(-(np.pi**2 * K * p * b * L**2) / (Sy * (ag * A) ** 2) * t)

    elif solution == "boussinesq":
        # Q(t) = [Q0^(-1/2) + beta * t]^(-2)
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
    t_min_days=1e-3,
    t_max_days=None,
):
    """
    Generate a full analytical discharge profile with automatic time scaling.

    Parameters
    ----------
    Q0 : float
        Initial discharge [m^3/s].
    K : float
        Hydraulic conductivity [m/s].
    Sy : float
        Specific yield [-].
    solution : str
        Analytical solution type: `"exponential"` or `"boussinesq"`.
    b : float or None
        Aquifer thickness [m], required for exponential solution.
    A : float or None
        Watershed area [m^2].
    L : float or None
        Channel length [m].
    ag : float
        Active drainage fraction [-].
    p : float
        Linearization constant [-].
    n_points : int
        Number of generated time points.
    log_spacing : bool
        If True, sample `t` in log space between `t_min_days` and `t_max_days`.
        If False, use linear spacing from 0 to `t_max_days`.
    t_min_days : float
        Lower bound in days for log-spaced sampling.
    t_max_days : float or None
        Upper bound in days. If None, defaults to `5 * tc`.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, float]
        `(t_seconds, t_days, q, tc_seconds)`.
    """
    # 1) Derive characteristic timescale from physical parameters.
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
        # Default horizon captures several characteristic times.
        t_max_days = 5.0 * tc / 86400.0

    # 2) Build temporal sampling grid.
    if log_spacing:
        if t_min_days <= 0:
            raise ValueError("t_min_days must be > 0 when log_spacing=True")
        if t_min_days >= t_max_days:
            raise ValueError("t_min_days must be < t_max_days")
        # Log spacing gives more resolution at early recession times.
        t_days = np.logspace(np.log10(t_min_days), np.log10(t_max_days), n_points)
    else:
        # Linear spacing includes time origin with constant step size.
        t_days = np.linspace(0, t_max_days, n_points)

    # 3) Convert days to seconds for analytical equations.
    t = t_days * 86400.0

    # 4) Evaluate analytical discharge profile on this grid.
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


def add_proportional_gaussian_error(values, error_fraction, random_seed=None):
    """
    Add Gaussian noise with pointwise proportional standard deviation.

    For each value x_i:
        epsilon_i ~ N(0, sigma_i^2)
        sigma_i = error_fraction * |x_i|

    Parameters
    ----------
    values : array-like
        Input values receiving noise.
    error_fraction : float
        Fraction controlling sigma as a proportion of each value.
        Must be >= 0.
    random_seed : int or None
        Optional seed for reproducibility.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray]
        `(values_noisy, noise, sigma)`.

    Notes
    -----
    This heteroscedastic noise model is often a better approximation than
    constant-variance noise for discharge-like quantities.
    """
    if error_fraction < 0:
        raise ValueError("error_fraction must be >= 0")

    x = np.asarray(values, dtype=float)
    # Each point gets its own sigma proportional to local magnitude.
    sigma = error_fraction * np.abs(x)
    rng = np.random.default_rng(random_seed)
    noise = rng.normal(loc=0.0, scale=sigma, size=x.shape)
    return x + noise, noise, sigma


def generate_noisy_baseflow_profile(
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
    t_min_days=1e-3,
    t_max_days=None,
    error_fraction=0.05,
    random_seed=None,
):
    """
    Generate analytical recession profile and add proportional Gaussian noise.

    Noise model for each point i:
        epsilon_i ~ N(0, sigma_i^2)
        sigma_i = error_fraction * |Q_i|
        Q_noisy_i = Q_i + epsilon_i

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, np.ndarray]
        `(t_seconds, t_days, q_true, q_noisy, tc_seconds, sigma)`.
    """
    # Step 1: deterministic analytical reference profile.
    t, t_days, q_true, tc = generate_baseflow_profile(
        Q0=Q0,
        K=K,
        Sy=Sy,
        solution=solution,
        b=b,
        A=A,
        L=L,
        ag=ag,
        p=p,
        n_points=n_points,
        log_spacing=log_spacing,
        t_min_days=t_min_days,
        t_max_days=t_max_days,
    )

    # Step 2: stochastic perturbation with proportional variance.
    q_noisy, _, sigma = add_proportional_gaussian_error(
        q_true,
        error_fraction=error_fraction,
        random_seed=random_seed,
    )
    return t, t_days, q_true, q_noisy, tc, sigma
