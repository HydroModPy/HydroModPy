"""Pydantic model for the ``[calibration]`` TOML section.

The TOML is deliberately minimal::

    [calibration]
    method       = "optuna"
    max_iter     = 200
    save_runs    = "best_n"
    save_best_n  = 10
    seed         = 42

    [calibration.parameters]
    K_aquifer  = { bounds = [1e-6, 1e-3], transform = "log" }
    Sy_main    = { bounds = [0.02, 0.30] }
    drain_cond = { bounds = [1e-4, 1e-1], transform = "log" }
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.profile import Profile
from hydromodpy.core.config.base import HydroModelBase


SaveRunsMode = Literal["none", "best_n", "all"]


class CalibParameterDecl(HydroModelBase):
    """Declaration of one calibratable parameter in the TOML."""

    model_config = ConfigDict(extra="forbid")

    bounds: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="[low, high] physical bounds. Inherits from Pydantic annotation when omitted.",
    )
    transform: Annotated[Literal["identity", "log", "logit"], Profile.USER] = Field(
        default="identity",
        description="Transform applied before sampling. 'log' for "
        "strictly-positive quantities spanning orders of magnitude.",
    )
    prior: Annotated[Literal["uniform", "log_uniform", "normal"], Profile.USER] = Field(
        default="uniform",
        description="Prior distribution used by Bayesian samplers.",
    )
    path: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Dotted path into HydroModPyConfig. Optional: when omitted, "
        "the caller is responsible for injection.",
    )
    units: Annotated[str | None, Profile.USER] = Field(
        default=None, description="Parameter units label."
    )


class CalibrationConfig(HydroModelBase):
    """Top-level ``[calibration]`` configuration."""

    model_config = ConfigDict(extra="forbid")

    method: Annotated[
        Literal["optuna", "scipy_de", "scipy_nelder_mead", "grid"],
        Profile.USER,
    ] = Field(
        default="optuna",
        description="Optimization method. 'optuna' is the recommended default.",
    )
    max_iter: Annotated[int, Profile.USER] = Field(
        default=100,
        ge=1,
        description="Maximum number of calibration iterations.",
    )
    batch_size: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Number of suggestions drawn per ask (for parallel optimizers).",
    )
    seed: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description="Random seed for reproducibility.",
    )
    save_runs: Annotated[SaveRunsMode, Profile.USER] = Field(
        default="none",
        description=(
            "How much to persist per iteration:\n"
            "- 'none': 1 DuckDB row per iteration, no Zarr.\n"
            "- 'best_n': same + promote top N to full simulations after the loop.\n"
            "- 'all': every iteration becomes a full simulation (Zarr included)."
        ),
    )
    save_best_n: Annotated[int, Profile.USER] = Field(
        default=10,
        ge=0,
        description="Number of top iterations to promote when save_runs='best_n'.",
    )
    use_cache: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Enable params_hash content-addressable cache.",
    )
    objective: Annotated[str, Profile.USER] = Field(
        default="nse",
        description="Metric key used by the default ScalarObjective.",
    )
    variable: Annotated[str, Profile.USER] = Field(
        default="head",
        description="Observed variable (for ObservationSet).",
    )
    optimizer_kwargs: Annotated[dict[str, Any], Profile.DEV] = Field(
        default_factory=dict,
        description="Extra keyword arguments forwarded to the optimizer adapter.",
    )
    parameters: Annotated[dict[str, CalibParameterDecl], Profile.USER] = Field(
        default_factory=dict,
        description="Per-parameter declarations (bounds, transform, prior, path).",
    )


__all__ = ["CalibrationConfig", "CalibParameterDecl", "SaveRunsMode"]
