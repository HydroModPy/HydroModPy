"""Pydantic model for the ``[calibration]`` TOML section.

Minimal TOML::

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

Enriched TOML (twin-benchmark style)::

    [calibration]
    method = "cma_es"
    max_iter = 80
    seed = 42

    [calibration.parameters.K_aquifer]
    bounds = [1e-6, 1e-3]
    target = "flow.param.K.field_homogeneous.value"
    mode = "replace"

    [calibration.outputs.head_A]
    variable = "head"
    support = "point"
    x = 100.0
    y = 0.0
    observed_values = [42.1, 41.8, 41.5]

    [[calibration.objective_blocks]]
    name = "head_block"
    metric = "rmse"
    weight = 1.0
    uses_outputs = ["head_A"]
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.units import Length

SaveRunsMode = Literal["none", "best_n", "all"]
ParameterMode = Literal["replace", "scale"]
OutputSupport = Literal["point", "boundary", "cell"]
OutputReducer = Literal["mean", "sum", "last", "none"]
ObjectiveTransform = Literal["identity", "log", "inverse"]
PersistIterationDetail = Literal["none", "summary", "full"]
MetricKind = Literal["rmse", "nse", "kge", "mae"]
CalibrationMethod = Literal[
    "optuna",
    "scipy_de",
    "scipy_nelder_mead",
    "grid",
    "grid_search",
    "random_search",
    "simplex",
    "cma_es",
    "nelder_mead",
    "gp_mapping",
    "da_mh_gp",
]


class CalibParameterDecl(HydroModelBase):
    """Declaration of one calibratable parameter in the TOML."""

    model_config = ConfigDict(extra="forbid")

    bounds: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        min_length=2,
        max_length=2,
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
    target: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Readable alias for 'path'. When both are set, 'target' wins.",
    )
    mode: Annotated[ParameterMode, Profile.USER] = Field(
        default="replace",
        description="'replace' writes the sampled value as-is; 'scale' multiplies "
        "the base TOML value at the target path by the sample.",
    )
    units: Annotated[str | None, Profile.USER] = Field(
        default=None, description="Parameter units label."
    )

    def resolve_target(self) -> str | None:
        """Return ``target`` when set, else ``path`` (read-only helper)."""
        return self.target if self.target is not None else self.path


class CalibOutputDecl(HydroModelBase):
    """Declaration of one observable extracted from a calibration run."""

    model_config = ConfigDict(extra="forbid")

    variable: Annotated[str, Profile.USER] = Field(
        description="Simulated variable to extract (e.g. 'head', 'outlet_discharge').",
    )
    support: Annotated[OutputSupport, Profile.USER] = Field(
        default="point",
        description="'point' reads at (x, y); 'boundary' sums flux at boundary_id; "
        "'cell' reads a single cell.",
    )
    x: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="X coordinate when support='point'. Accepts a bare number "
        "(metres) or a pint string like '100 m'.",
    )
    y: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Y coordinate when support='point'. Accepts a bare number "
        "(metres) or a pint string like '100 m'.",
    )
    boundary_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Boundary package identifier when support='boundary'.",
    )
    time: Annotated[Literal["all", "last", "first"] | list[str], Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one; "
        "a list of ISO timestamps selects specific steps.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="Aggregation over the retained time slice.",
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values (used by twin-synthetic cases).",
    )

    @model_validator(mode="after")
    def _check_support_required_fields(self) -> CalibOutputDecl:
        if self.support == "point" and (self.x is None or self.y is None):
            raise ValueError("support='point' requires both 'x' and 'y' to be set.")
        if self.support == "boundary" and self.boundary_id is None:
            raise ValueError("support='boundary' requires 'boundary_id' to be set.")
        return self


class CalibObjectiveBlockDecl(HydroModelBase):
    """Declaration of one weighted block inside a composite objective."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Profile.USER] = Field(
        description="Unique block identifier used in logs and persistence.",
    )
    metric: Annotated[MetricKind, Profile.USER] = Field(
        default="rmse",
        description="Metric key. One of rmse, nse, kge, mae.",
    )
    weight: Annotated[float, Profile.USER] = Field(
        default=1.0,
        gt=0.0,
        description="Relative weight of this block in the composite sum.",
    )
    uses_outputs: Annotated[list[str], Profile.USER] = Field(
        min_length=1,
        description="Outputs (by name) consumed by this block.",
    )
    normalize_cost: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="When True, divide the block cost by a reference scale "
        "(observed std fallback mean absolute value).",
    )
    transform: Annotated[ObjectiveTransform, Profile.USER] = Field(
        default="identity",
        description="Per-block cost transform applied before weighting.",
    )


class CalibrationConfig(HydroModelBase):
    """Top-level ``[calibration]`` configuration."""

    model_config = ConfigDict(extra="forbid")

    method: Annotated[CalibrationMethod, Profile.USER] = Field(
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
    outputs: Annotated[dict[str, CalibOutputDecl], Profile.USER] = Field(
        default_factory=dict,
        description="Named observables extracted from each candidate run.",
    )
    objective_blocks: Annotated[list[CalibObjectiveBlockDecl], Profile.USER] = Field(
        default_factory=list,
        description="Weighted blocks making up a composite objective. When empty, "
        "a single implicit block is built from 'objective' and 'variable'.",
    )
    persist_iteration_detail: Annotated[PersistIterationDetail, Profile.DEV] = Field(
        default="summary",
        description="'none' skips component metrics; 'summary' keeps block totals; "
        "'full' also stores per-block raw and normalized costs.",
    )
    persist_model_distribution: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Persist the candidate distribution alongside the session.",
    )
    resume_session: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Session id to resume. When set, prior iterations seed the loop.",
    )
    rerun_best_with_outputs: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Replay the best candidate with full outputs after the loop.",
    )
    materialize_candidates: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Write a standalone override TOML for each candidate under "
        "'candidates_root' so runs can be replayed later.",
    )
    candidates_root: Annotated[PurePosixPath | None, Profile.DEV] = Field(
        default=None,
        description="Directory for per-candidate overlay TOMLs. "
        "Required when materialize_candidates is True.",
    )

    @field_validator("candidates_root", mode="before")
    @classmethod
    def _normalize_candidates_root(cls, value: Any) -> PurePosixPath | None:
        """Keep user-provided TOML paths stable across host OS path flavors."""
        if value is None:
            return None
        if isinstance(value, PurePosixPath):
            return value
        if isinstance(value, Path):
            return PurePosixPath(value.as_posix())
        return PurePosixPath(str(value).replace("\\", "/"))

    @model_validator(mode="after")
    def _ensure_implicit_objective_block(self) -> CalibrationConfig:
        """Build an implicit block from (objective, variable) when none is declared."""
        if not self.objective_blocks:
            variable = self.variable
            implicit_output = self.outputs.get(variable)
            if implicit_output is None:
                return self
            implicit = CalibObjectiveBlockDecl(
                name=f"{self.objective}_{variable}",
                metric=self.objective,
                weight=1.0,
                uses_outputs=[variable],
            )
            self.objective_blocks = [implicit]
        return self

    @model_validator(mode="after")
    def _check_uses_outputs_reference_declared(self) -> CalibrationConfig:
        if not self.objective_blocks:
            return self
        declared = set(self.outputs)
        if not declared:
            return self
        for block in self.objective_blocks:
            unknown = [name for name in block.uses_outputs if name not in declared]
            if unknown:
                raise ValueError(
                    f"objective_block {block.name!r} uses_outputs={unknown!r} "
                    f"but those names are not declared in [calibration.outputs]. "
                    f"Declared outputs: {sorted(declared)}."
                )
        return self

    @model_validator(mode="after")
    def _check_candidates_root_required(self) -> CalibrationConfig:
        if self.materialize_candidates and self.candidates_root is None:
            raise ValueError("materialize_candidates=True requires candidates_root to be set.")
        return self


__all__ = [
    "CalibrationConfig",
    "CalibParameterDecl",
    "CalibOutputDecl",
    "CalibObjectiveBlockDecl",
    "SaveRunsMode",
    "ParameterMode",
    "OutputSupport",
    "OutputReducer",
    "ObjectiveTransform",
    "PersistIterationDetail",
    "CalibrationMethod",
    "MetricKind",
]
