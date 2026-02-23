"""Structured calibration-result container for reference-case workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np


_CORE_METHOD_OUTPUT_KEYS = {
    "method",
    "x_best",
    "cost_best",
    "n_evaluations",
    "posterior_samples",
    "samples",
}


def _as_1d_float_array(values, name):
    """Convert values to a non-empty 1D float array."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{name} cannot be empty")
    return arr


def _as_samples_array(values, n_dim, name):
    """Convert optional values to a 2D float sample matrix `(n_samples, n_dim)`."""
    if values is None:
        return None

    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return None

    if arr.ndim == 1:
        if n_dim == 1:
            arr = arr.reshape(-1, 1)
        elif arr.size == n_dim:
            arr = arr.reshape(1, n_dim)
        else:
            raise ValueError(
                f"{name} must be 2D with shape (n_samples, {n_dim}) "
                f"or a single sample of length {n_dim}"
            )

    if arr.ndim != 2:
        raise ValueError(f"{name} must be a 2D array")
    if arr.shape[1] != n_dim:
        raise ValueError(
            f"{name} second dimension must be {n_dim}, got {arr.shape[1]}"
        )
    if arr.shape[0] == 0:
        return None
    return arr


@dataclass(slots=True)
class CalibrationResults:
    """
    Canonical calibration output.

    Attributes
    ----------
    method : str
        Calibration method key.
    x_best : np.ndarray
        Best parameter vector found by the method.
    params_best : dict[str, float] | None
        Optional named best-parameter mapping in canonical parameter order.
    cost_best : float
        Best objective cost.
    score_best : float | None
        Optional objective score at `x_best`.
    n_evaluations : int
        Number of expensive objective evaluations.
    samples : np.ndarray | None
        Optional posterior/uncertainty samples with shape `(n_samples, n_dim)`.
    metadata : dict[str, object]
        Additional method-specific outputs/diagnostics.
    """

    method: str
    x_best: np.ndarray
    params_best: dict[str, float] | None
    cost_best: float
    score_best: float | None
    n_evaluations: int
    samples: np.ndarray | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        self.method = str(self.method).strip()
        if not self.method:
            raise ValueError("method cannot be empty")

        self.x_best = _as_1d_float_array(self.x_best, "x_best")
        self.cost_best = float(self.cost_best)
        if self.score_best is not None:
            self.score_best = float(self.score_best)
        self.n_evaluations = int(self.n_evaluations)
        if self.n_evaluations < 0:
            raise ValueError("n_evaluations must be >= 0")

        if self.params_best is None:
            self.params_best = None
        else:
            named = dict(self.params_best)
            if len(named) != self.x_best.size:
                raise ValueError(
                    "params_best size must match x_best dimension "
                    f"({len(named)} vs {self.x_best.size})"
                )
            self.params_best = {str(k): float(v) for k, v in named.items()}

        self.samples = _as_samples_array(self.samples, self.x_best.size, "samples")
        self.metadata = dict(self.metadata)

    @property
    def has_samples(self):
        """Return True when distribution samples are available."""
        return self.samples is not None and self.samples.shape[0] > 0

    @property
    def n_samples(self):
        """Number of available distribution samples."""
        if self.samples is None:
            return 0
        return int(self.samples.shape[0])

    @classmethod
    def from_method_output(
        cls,
        method_output,
        *,
        default_method,
    ):
        """
        Build a canonical result object from method output.
        """
        if isinstance(method_output, cls):
            return method_output
        if not isinstance(method_output, Mapping):
            raise TypeError("method output must be a mapping")

        output = dict(method_output)
        method = str(output.get("method", default_method))
        x_best = _as_1d_float_array(output["x_best"], "x_best")
        cost_best = float(output["cost_best"])
        n_evaluations = int(output.get("n_evaluations", -1))
        if n_evaluations < 0:
            raise ValueError("method output must provide n_evaluations >= 0")

        samples = _as_samples_array(
            output.get("posterior_samples"),
            x_best.size,
            "posterior_samples",
        )
        chain_samples = _as_samples_array(
            output.get("samples"),
            x_best.size,
            "samples",
        )
        if samples is None:
            samples = chain_samples

        metadata = {
            key: value
            for key, value in output.items()
            if key not in _CORE_METHOD_OUTPUT_KEYS
        }
        if (
            output.get("posterior_samples") is not None
            and chain_samples is not None
        ):
            metadata["chain_samples"] = chain_samples

        return cls(
            method=method,
            x_best=x_best,
            params_best=None,
            cost_best=cost_best,
            score_best=None,
            n_evaluations=n_evaluations,
            samples=samples,
            metadata=metadata,
        )

    def attach_context(self, *, vector_to_params, score_best):
        """
        Attach engine-level context (`params_best`, `score_best`) in-place.
        """
        if self.params_best is None:
            named = dict(vector_to_params(self.x_best))
            if len(named) != self.x_best.size:
                raise ValueError(
                    "vector_to_params returned an inconsistent mapping size "
                    f"({len(named)} vs {self.x_best.size})"
                )
            self.params_best = {str(k): float(v) for k, v in named.items()}
        if self.score_best is None:
            self.score_best = float(score_best)
        return self
