"""A linearized covariance around the answer a search returned.

The search says where the optimum is. This says how wide it is, and it is the only
declared method that also says which parameters trade off against which: a
conductivity and a storage that compensate each other are not two numbers known to
ten per cent, they are one number and a ratio, and a calibration that reports the
first reading has told the reader the wrong thing.

The arithmetic is first-order, and that word is the whole caveat. The model is
linearized about the optimum, so the covariance is exact where the model is linear
there and approximate in proportion to how curved it is. It is not a posterior: it
carries no prior and states nothing about probability beyond the propagation of a
residual variance through one derivative.

What it costs: one model run per parameter, forward differences about the optimum.
That is cheaper than restarting the whole search, which is why it exists beside
``multistart`` rather than instead of it.

The constraint obeyed here is the project's: the calibrated value is untouched. This
reads derivatives around it and reports a width beside it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ParameterUncertainty:
    """How wide one calibrated value is, and what it trades off against."""

    parameter: str
    value: float
    sigma: float
    correlations: Mapping[str, float]

    @property
    def relative_sigma(self) -> float | None:
        """Sigma as a fraction of the value, or None when the value is zero."""
        if self.value == 0.0:
            return None
        return abs(self.sigma / self.value)

    def strongest_tradeoff(self) -> tuple[str, float] | None:
        """Return the parameter this one is most correlated with, and how much.

        A reader needs this more than the sigma: two parameters at 0.99 were not
        identified separately, whatever their individual widths say.
        """
        others = {
            name: value for name, value in self.correlations.items() if name != self.parameter
        }
        if not others:
            return None
        name = max(others, key=lambda key: abs(others[key]))
        return name, float(others[name])

    def to_dict(self) -> dict[str, object]:
        tradeoff = self.strongest_tradeoff()
        return {
            "parameter": self.parameter,
            "value": self.value,
            "sigma": self.sigma,
            "relative_sigma": self.relative_sigma,
            "strongest_tradeoff": None
            if tradeoff is None
            else {
                "parameter": tradeoff[0],
                "correlation": tradeoff[1],
            },
        }


def forward_difference_jacobian(
    names: Sequence[str],
    reference: Mapping[str, float],
    simulate: Callable[[Mapping[str, float]], np.ndarray],
    *,
    relative_step: float = 0.01,
) -> np.ndarray:
    """Return the (n_obs, n_par) derivative of the simulated vector.

    ``simulate`` runs the model at one parameter set and returns its value at each
    observation, in a fixed order. One run per parameter, plus the reference one the
    caller has already paid for.

    A parameter the simulated vector does not respond to gives a column of zeros,
    which is not an error: it is the statement that this calibration could not see
    that parameter, and the covariance says so by refusing to invert.
    """
    step_of = {}
    base = np.asarray(simulate(reference), dtype=float).ravel()
    columns = []
    for name in names:
        step = _step_for(float(reference[name]), relative_step)
        step_of[name] = step
        moved = dict(reference)
        moved[name] = float(reference[name]) + step
        perturbed = np.asarray(simulate(moved), dtype=float).ravel()
        if perturbed.size != base.size:
            raise ValueError(
                f"perturbing {name!r} returned {perturbed.size} simulated value(s) and the "
                f"reference returned {base.size}; a Jacobian needs the same observations in "
                "the same order at every run."
            )
        columns.append((perturbed - base) / step)
    return np.column_stack(columns) if columns else np.empty((base.size, 0))


def _step_for(value: float, relative_step: float) -> float:
    """Return a finite-difference step that is neither zero nor absurd."""
    if relative_step <= 0.0:
        raise ValueError(f"the perturbation has to be positive, got {relative_step!r}.")
    step = abs(value) * relative_step
    # A parameter sitting at zero has no scale of its own to take a fraction of.
    return step if step > 0.0 else relative_step


def linearized_covariance(jacobian: np.ndarray, residuals: np.ndarray) -> np.ndarray:
    """Return the first-order parameter covariance, ``sigma2 * inv(J' J)``.

    The residual variance is the sum of squares over the degrees of freedom, which
    is what makes this a covariance of the fit and not of the observations. Fewer
    observations than parameters is refused rather than regularised: there is no
    width to report from a fit with nothing left over.
    """
    J = np.asarray(jacobian, dtype=float)
    r = np.asarray(residuals, dtype=float).ravel()
    n_obs, n_par = J.shape
    if r.size != n_obs:
        raise ValueError(
            f"the Jacobian holds {n_obs} observation(s) and the residual vector {r.size}; "
            "they have to be the same observations."
        )
    dof = n_obs - n_par
    if dof <= 0:
        raise ValueError(
            f"{n_obs} observation(s) and {n_par} parameter(s) leave {dof} degree(s) of "
            "freedom: a linearized covariance needs at least one, because the residual "
            "variance is what gives it its scale."
        )
    normal = J.T @ J
    try:
        inverse = np.linalg.inv(normal)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "the normal matrix J'J is singular, so this calibration did not identify its "
            "parameters separately: at least one of them moves the simulated values in a "
            "way another one can reproduce exactly. Report the value, not a width."
        ) from exc
    sigma2 = float(r @ r) / dof
    return sigma2 * inverse


def uncertainty_from_covariance(
    names: Sequence[str], values: Mapping[str, float], covariance: np.ndarray
) -> tuple[ParameterUncertainty, ...]:
    """Turn a covariance into one statement per parameter, with its correlations."""
    C = np.asarray(covariance, dtype=float)
    sigmas = np.sqrt(np.clip(np.diag(C), 0.0, None))
    out: list[ParameterUncertainty] = []
    for index, name in enumerate(names):
        correlations = {}
        for other, other_index in zip(names, range(len(names)), strict=True):
            denominator = sigmas[index] * sigmas[other_index]
            correlations[other] = (
                float(C[index, other_index] / denominator) if denominator > 0.0 else 0.0
            )
        out.append(
            ParameterUncertainty(
                parameter=name,
                value=float(values[name]),
                sigma=float(sigmas[index]),
                correlations=correlations,
            )
        )
    return tuple(out)


__all__ = [
    "ParameterUncertainty",
    "forward_difference_jacobian",
    "linearized_covariance",
    "uncertainty_from_covariance",
]
