"""Pydantic model for the ``[calibration]`` TOML section.

Minimal TOML::

    [calibration]
    method       = "grid"
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
    target = "flow.param.K.field.value"
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
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, TypeAdapter, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr, NonNegativeInt, PositiveFloat
from hydromodpy.core.units import Length

SaveRunsMode = Literal["none", "best_n", "all"]
ParameterMode = Literal["replace", "scale"]
OutputSupport = Literal["point", "boundary", "cell", "lake", "network"]
OutputReducer = Literal["mean", "sum", "last", "none"]
ObjectiveTransform = Literal["identity", "log", "inverse"]
PersistIterationDetail = Literal["none", "summary", "full"]
MetricKind = Literal["rmse", "nse", "kge", "mae", "nse_log", "distance_gap", "distance_mean"]
CalibrationMethod = NonEmptyStr
OutputTime = Literal["all", "last", "first"] | list[str]


class CalibParameterDecl(HydroModelBase):
    """User declaration for one calibrated parameter.

    The declaration is read from ``[calibration.parameters.<name>]``. It
    defines the physical bounds, the sampling transform, and optionally the
    target path in ``HydroModPyConfig`` that receives each sampled value.

    Use ``mode="replace"`` for direct parameter values and ``mode="scale"``
    for multiplicative factors applied to an existing config value.
    """

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


class CalibOutputPoint(HydroModelBase):
    """Observable extracted at a planar ``(x, y)`` point.

    Use this variant for piezometric heads sampled at a single coordinate.
    Provide either ``x`` and ``y`` or a GeoJSON ``geometry`` block.
    """

    variable: Annotated[str, Profile.USER] = Field(
        description="Simulated variable to extract (e.g. 'head', 'outlet_discharge').",
    )
    support: Annotated[Literal["point"], Profile.USER] = Field(
        default="point",
        description="Discriminator tag. 'point' reads the variable at (x, y).",
    )
    geometry: Annotated[dict[str, Any] | None, Profile.USER] = Field(
        default=None,
        description="GeoJSON point geometry. Coordinates are in metres.",
    )
    x: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="X coordinate. Accepts a bare number (metres) or a pint string like '100 m'.",
    )
    y: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Y coordinate. Accepts a bare number (metres) or a pint string like '100 m'.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
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
    def _check_point_selectors(self) -> CalibOutputPoint:
        if (self.x is None or self.y is None) and self.geometry is None:
            raise ValueError("support='point' requires both 'x' and 'y', or 'geometry'.")
        return self


class CalibOutputBoundary(HydroModelBase):
    """Observable extracted from a boundary package.

    Use this variant for fluxes integrated over a named boundary
    (drains, rivers, GHB) referenced by ``boundary_id``.
    """

    variable: Annotated[str, Profile.USER] = Field(
        description="Simulated variable to extract (e.g. 'discharge').",
    )
    support: Annotated[Literal["boundary"], Profile.USER] = Field(
        default="boundary",
        description="Discriminator tag. 'boundary' sums flux at boundary_id.",
    )
    boundary_id: Annotated[str, Profile.USER] = Field(
        description="Boundary package identifier.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
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


class CalibOutputCell(HydroModelBase):
    """Observable extracted at one structured cell.

    Use this variant for explicit ``(row, col)`` selectors on a structured
    grid, optionally with a non-zero ``layer``. ``cell_id`` is a flat index
    accepted on backends that expose one.
    """

    variable: Annotated[str, Profile.USER] = Field(
        description="Simulated variable to extract (e.g. 'head').",
    )
    support: Annotated[Literal["cell"], Profile.USER] = Field(
        default="cell",
        description="Discriminator tag. 'cell' reads one structured cell.",
    )
    cell_id: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Flat cell index when the backend exposes one.",
    )
    row: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Structured row index.",
    )
    col: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Structured column index.",
    )
    layer: Annotated[NonNegativeInt, Profile.USER] = Field(
        default=0,
        description="Structured layer index.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
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
    def _check_cell_selectors(self) -> CalibOutputCell:
        if self.cell_id is None and (self.row is None or self.col is None):
            raise ValueError("support='cell' requires 'cell_id' or both 'row' and 'col'.")
        return self


class CalibOutputLake(HydroModelBase):
    """Observable extracted from a MODFLOW 6 LAK lake state.

    Use this variant to score a lake water level, stored volume or free surface
    inside a composite objective. ``lake_id`` matches the lake declared under
    ``flow.sinks_sources.lakes.<lake_id>``.

    For calibration against a real observed chronicle, prefer the top-level
    ``variable = "lake_level"`` path: it loads the ``lake_levels`` data family
    and time-aligns the simulated stage to the observations. This output
    variant scores positionally against ``observed_values``, like the other
    composite outputs.
    """

    variable: Annotated[Literal["stage", "volume", "surface_area"], Profile.USER] = Field(
        default="stage",
        description=(
            "Simulated lake quantity: 'stage' (water level, m), 'volume' (m3) or "
            "'surface_area' (m2). All three are LAK observation states, read in native "
            "units and never time-scaled."
        ),
    )
    support: Annotated[Literal["lake"], Profile.USER] = Field(
        default="lake",
        description="Discriminator tag. 'lake' reads a LAK lake stage by lake_id.",
    )
    lake_id: Annotated[str, Profile.USER] = Field(
        description="Lake identifier, matching flow.sinks_sources.lakes.<lake_id>.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
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


class CalibOutputNetwork(HydroModelBase):
    """The mapped stream network as a calibration target.

    The model is compared to a hydrographic network rather than to a gauge:
    for every cell where it releases water to the surface, the descent to the
    mapped network is measured, and reciprocally. The output produces the pair
    ``(D_so, D_os)``; the metric on top of it is ``distance_gap``, their signed
    difference in absolute value, whose zero is the balance between an excess
    of simulated stream and a missing one.

    ``observed_values`` is not asked of the user and defaults to a pair of
    zeros: the criterion balances two simulated quantities against each other,
    so there is no observed vector to fit. The mapped network enters through
    ``stream_geometry_path``, as a geometry, not as a series.
    """

    variable: Annotated[str, Profile.USER] = Field(
        default="release_flux",
        description="Per-cell observable read from the solver, in m3/s, positive "
        "when the aquifer feeds the surface.",
    )
    support: Annotated[Literal["network"], Profile.USER] = Field(
        default="network",
        description="Discriminator: compare a simulated stream network to a mapped one.",
    )
    stream_geometry_path: Annotated[str, Profile.USER] = Field(
        description="Vector file holding the mapped stream network. Required, and "
        "read only from here: the criterion resolves no geometry of its own and "
        "does not reuse the one the hydrography data family loaded.",
    )
    tau_specific_ratio: Annotated[float, Profile.USER] = Field(
        default=1.0e-4,
        ge=0.0,
        description="A cell releasing less than this fraction of its own recharge is "
        "not a seepage face. Zero reproduces the purely geometric criterion of the "
        "paper. Frozen over the whole search: a threshold moving with the trial would "
        "cost the criterion its monotonicity.",
    )
    weighting: Annotated[Literal["cell", "area"], Profile.USER] = Field(
        default="cell",
        description="Average one cell one vote (the paper) or weighted by cell area. "
        "Both values are always reported; use 'area' on a mesh refined along the "
        "streams, where cell density is highest exactly where distances are smallest.",
    )
    diagonal_neighbors: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Route over shared nodes rather than shared edges, which recovers "
        "the diagonal descents of a D8 grid. Only meaningful on a structured quad mesh.",
    )
    observed_position_accuracy: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Positional accuracy of the mapped network. The validity ratio is "
        "normalised by max(cell size, this), because the error floor is set by the "
        "network's own precision and not by the model resolution. Unset is the "
        "literal reading of the paper.",
    )
    roptim_max: Annotated[PositiveFloat, Profile.USER] = Field(
        default=2.0,
        description="Validity bound of Eq. 4. It qualifies the result and never "
        "penalises the cost: a bad ratio says the agreement is coarse, not that the "
        "calibrated value should be discarded.",
    )
    on_roptim_violation: Annotated[Literal["warn", "error"], Profile.USER] = Field(
        default="warn",
        description="What a violation of the validity bound does. Default warns and "
        "returns the value, because a calibration is asked for a number.",
    )
    max_unreachable_fraction: Annotated[float, Profile.USER] = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Share of a support whose descent may end without meeting its "
        "target before the trial fails. Beyond a few per cent the surface is not "
        "conditioned and the averages would be a fiction.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="last",
        description="Which timesteps the release flux is read at. Phase one runs a "
        "single steady period, so 'last' is the whole run.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="Kept for symmetry with the other supports; the pair this output "
        "produces is already reduced.",
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Structurally absent: the criterion balances two simulated "
        "quantities. Defaults to a pair of zeros so a block can be declared on it.",
    )

    @model_validator(mode="after")
    def _default_observed_pair(self) -> CalibOutputNetwork:
        if self.observed_values is None:
            self.observed_values = [0.0, 0.0]
        elif len(self.observed_values) != 2:
            raise ValueError(
                "a network output produces the pair (D_so, D_os); observed_values must "
                f"hold two entries, got {len(self.observed_values)}."
            )
        return self


CalibOutputDecl: TypeAlias = Annotated[
    CalibOutputPoint | CalibOutputBoundary | CalibOutputCell | CalibOutputLake | CalibOutputNetwork,
    Field(
        discriminator="support",
        description="Discriminated union of calibration output variants selected by 'support'.",
    ),
]
"""Discriminated union of calibration output schemas keyed by ``support``."""


_CALIB_OUTPUT_ADAPTER: TypeAdapter[CalibOutputDecl] = TypeAdapter(CalibOutputDecl)


def validate_calib_output(
    payload: Any,
) -> (
    CalibOutputPoint | CalibOutputBoundary | CalibOutputCell | CalibOutputLake | CalibOutputNetwork
):
    """Validate one output mapping and return the concrete variant instance."""
    return _CALIB_OUTPUT_ADAPTER.validate_python(payload)


class CalibScoringWindow(HydroModelBase):
    """Dates bounding the samples a metric is computed on.

    A window in dates rather than in sample counts: it says the same thing
    whatever the output frequency, whereas ``warmup_periods`` counts samples
    after alignment and therefore means a different span at daily and at weekly
    resolution. The two are mutually exclusive, which
    :class:`CalibrationConfig` enforces.
    """

    start: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="First date scored, ISO 8601. Unset means from the first sample.",
    )
    end: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Last date scored, ISO 8601. Unset means up to the last sample.",
    )

    @model_validator(mode="after")
    def _check_bounds(self) -> CalibScoringWindow:
        bounds = _parsed_scoring_bounds(self)
        if bounds[0] is not None and bounds[1] is not None and bounds[0] > bounds[1]:
            raise ValueError(f"scoring_window start {self.start!r} is after end {self.end!r}.")
        return self


def _parsed_scoring_bounds(window: CalibScoringWindow) -> tuple[Any, Any]:
    """Parse the window bounds into timestamps, raising on a bad date."""
    import pandas as pd

    parsed = []
    for label, raw in (("start", window.start), ("end", window.end)):
        if raw is None:
            parsed.append(None)
            continue
        try:
            parsed.append(pd.Timestamp(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scoring_window {label}={raw!r} is not a date.") from exc
    return parsed[0], parsed[1]


def scoring_window_bounds(window: CalibScoringWindow | None) -> tuple[Any, Any] | None:
    """Return the parsed ``(start, end)`` of a window, or None when unset."""
    if window is None:
        return None
    return _parsed_scoring_bounds(window)


class CalibObjectiveBlockDecl(HydroModelBase):
    """Weighted metric block used by a composite objective.

    A block consumes one or more named outputs, applies one metric, and
    contributes ``weight`` to the final minimization cost. Blocks make mixed
    objectives explicit, for example combining heads, discharge, and transport
    signals in one calibration session.
    """

    name: Annotated[str, Profile.USER] = Field(
        description="Unique block identifier used in logs and persistence.",
    )
    metric: Annotated[MetricKind, Profile.USER] = Field(
        default="rmse",
        description="Metric key. One of rmse, nse, kge, mae, nse_log.",
    )
    weight: Annotated[PositiveFloat, Profile.USER] = Field(
        default=1.0,
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
        description="Per-block cost transform applied before weighting. Note that "
        "transform='log' takes the logarithm of the cost, which is not the same "
        "thing as metric='nse_log', an NSE computed on log-transformed series.",
    )
    warmup: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description=(
            "Burn-in periods dropped from this block only, overriding "
            "[calibration].warmup_periods. Leave unset to inherit it; set it to 0 to "
            "switch the burn-in off for this block."
        ),
    )


class CalibPhaseDecl(HydroModelBase):
    """One stage of a calibration that runs in several.

    A phase selects, by name, from the parameters, outputs and objective blocks
    the calibration already declares: nothing is redeclared, so the two stages
    of a method cannot drift apart in a single file. What a phase carries of
    its own is its search: a method, a budget, and which parameters it is
    allowed to move.

    ``freeze_on_success`` means the parameters this phase calibrated are held
    fixed for the phases that depend on it. It reads "freeze if the phase
    converged", never "freeze if the result is good": a validity indicator
    qualifies a result, and a phase that returns a coarse agreement still
    returns a number. The state of that indicator travels to the dependent
    phase and into the report, so a value calibrated on top of a doubtful one
    carries the mention all the way out.
    """

    name: Annotated[NonEmptyStr, Profile.USER] = Field(
        description="Phase identifier, unique in the calibration and used in the "
        "session directory and in the report.",
    )
    description: Annotated[str, Profile.USER] = Field(
        default="",
        description="What this phase calibrates and against what, in one sentence.",
    )
    method: Annotated[CalibrationMethod, Profile.USER] = Field(
        default="grid",
        description="Optimization method for this phase only.",
    )
    max_iter: Annotated[int, Profile.USER] = Field(
        default=100,
        ge=1,
        description="Maximum number of evaluations for this phase.",
    )
    batch_size: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Suggestions drawn per ask. A root search returns one point at a "
        "time during its refinement, whatever this asks for.",
    )
    parallel: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Trials evaluated concurrently inside one batch.",
    )
    parameters: Annotated[list[str], Profile.USER] = Field(
        min_length=1,
        description="Names of the calibration parameters this phase may move. Every "
        "other parameter keeps the value it entered the phase with.",
    )
    outputs: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Names of the calibration outputs this phase scores on. Empty "
        "means every declared output.",
    )
    objective_blocks: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Names of the objective blocks this phase evaluates. Empty means "
        "every declared block.",
    )
    variable: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Single-metric variable, when this phase does not use blocks.",
    )
    objective: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Single-metric objective, when this phase does not use blocks.",
    )
    optimizer_kwargs: Annotated[dict[str, Any], Profile.DEV] = Field(
        default_factory=dict,
        description="Extra keyword arguments forwarded to this phase's optimizer.",
    )
    overrides: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="Configuration values this phase runs with, as dotted paths into "
        "the project configuration. The two stages of a stream-network calibration "
        "are one steady and one transient, which is a property of the model and not "
        "of the search, so a phase has to be able to say it.",
    )
    scoring_window: Annotated[CalibScoringWindow | None, Profile.USER] = Field(
        default=None,
        description="Dates bounding the samples this phase scores on.",
    )
    depends_on: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Name of the phase that must run first. Its frozen parameters "
        "enter this one as fixed values.",
    )
    freeze_on_success: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Hold the parameters this phase calibrated fixed for the phases "
        "that depend on it. Success means the phase converged, not that its validity "
        "indicator is good.",
    )

    @property
    def is_single_metric(self) -> bool:
        """Whether this phase scores one variable rather than objective blocks.

        Declaring ``variable`` or ``objective`` picks the single-metric route.
        The phase then ignores the outputs and the blocks the calibration
        declares for the other phases, which would otherwise take precedence
        and score it on a criterion it never asked for.
        """
        return self.variable is not None or self.objective is not None


class CalibrationConfig(HydroModelBase):
    """Top-level ``[calibration]`` section.

    The config selects the optimizer, iteration budget, candidate persistence
    policy, parameter declarations, observable outputs, and objective blocks.
    It is the stable user-facing schema used by CLI calibration and
    ``Project.calibrate``.

    When no explicit objective block is declared, HydroModPy can synthesize one
    from ``objective`` and ``variable`` if the matching output exists.
    """

    method: Annotated[CalibrationMethod, Profile.USER] = Field(
        default="grid",
        description=(
            "Optimization method. Optuna is installed by default; install the "
            "calibration extra for cma_es and Optuna's cmaes sampler."
        ),
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
    parallel: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description=(
            "Number of trials evaluated concurrently inside one batch via a "
            "thread pool. parallel=1 keeps the legacy sequential loop."
        ),
    )
    warmup_periods: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        description=(
            "Spin-up (burn-in) periods excluded from every objective block. The first "
            "warmup_periods of each observed/simulated series are dropped before the "
            "metric, so the window where the state still depends on the initial condition "
            "does not bias the calibration. Default 0 (no exclusion). Size it by "
            "increasing it until the objective stops changing (initial-condition "
            "insensitivity), not a fixed guess."
        ),
    )
    scoring_window: Annotated[CalibScoringWindow | None, Profile.USER] = Field(
        default=None,
        description=(
            "Dates bounding the samples every metric is computed on. Mutually "
            "exclusive with warmup_periods, which counts samples instead of dates."
        ),
    )
    phases: Annotated[list[CalibPhaseDecl] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Stages run one after the other, each calibrating its own parameters and "
            "freezing them for the next. Declaring this table is what switches the "
            "runner to staged mode; without it nothing changes for an existing "
            "configuration. The default is None and not an empty list on purpose: the "
            "resume lock hashes the configuration with exclude_none, so an absent "
            "table leaves that hash untouched and checkpoints stay resumable."
        ),
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
    lightweight_extraction: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Skip Parquet/Zarr writes for lumped models (GR4J, ...) and "
        "read simulated series from the per-trial RAM cache instead. Only the "
        "promoted runs go through the catalog write path.",
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
    persistence: Annotated[PersistenceConfig, Profile.USER] = Field(
        default_factory=PersistenceConfig,
        description="Single switch governing every persistence sink "
        "(catalog, Zarr, Parquet, lockfile) for calibration outputs.",
    )

    def validate_registry(self) -> None:
        """Verify the selected method is registered and its kwargs validate.

        The discriminated union :data:`CalibrationMethodConfig` raises eagerly
        when ``optimizer_kwargs`` carries keys foreign to ``method`` so the
        failure happens at config-load time instead of inside the adapter
        constructor.
        """
        from hydromodpy.calibration.optim.method_config import validate_method_kwargs
        from hydromodpy.calibration.optim.optimizer import available_optimizers

        available = available_optimizers()
        if self.method not in available:
            raise ValueError(
                f"Unknown calibration method {self.method!r}. Available methods: {available}"
            )
        validate_method_kwargs(self.method, self.optimizer_kwargs)

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
    def _check_phases(self) -> CalibrationConfig:
        """Refuse a phase table that cannot run, before the first solve."""
        phases = self.phases or []
        if not phases:
            return self

        seen: list[str] = []
        for phase in phases:
            if phase.name in seen:
                raise ValueError(f"phase {phase.name!r} is declared twice.")
            seen.append(phase.name)

        declared_parameters = set(self.parameters)
        declared_outputs = set(self.outputs)
        declared_blocks = {block.name for block in self.objective_blocks}
        frozen_by: dict[str, str] = {}

        for index, phase in enumerate(phases):
            unknown = sorted(set(phase.parameters) - declared_parameters)
            if unknown:
                raise ValueError(
                    f"phase {phase.name!r} calibrates undeclared parameter(s) {unknown}; "
                    f"declared: {sorted(declared_parameters)}."
                )
            for parameter in phase.parameters:
                path = self.parameters[parameter].resolve_target()
                if not path:
                    raise ValueError(
                        f"phase {phase.name!r} calibrates {parameter!r}, which declares "
                        "no path into the configuration, so nothing would be injected."
                    )
                if phase.freeze_on_success:
                    owner = frozen_by.get(path)
                    if owner is not None:
                        raise ValueError(
                            f"phases {owner!r} and {phase.name!r} both freeze {path!r}; "
                            "the second would overwrite what the first calibrated."
                        )
                    frozen_by[path] = phase.name

            unknown_outputs = sorted(set(phase.outputs) - declared_outputs)
            if unknown_outputs:
                raise ValueError(
                    f"phase {phase.name!r} scores on undeclared output(s) {unknown_outputs}."
                )
            unknown_blocks = sorted(set(phase.objective_blocks) - declared_blocks)
            if unknown_blocks:
                raise ValueError(
                    f"phase {phase.name!r} uses undeclared objective block(s) {unknown_blocks}."
                )

            if phase.depends_on is not None:
                if phase.depends_on not in seen[:index]:
                    raise ValueError(
                        f"phase {phase.name!r} depends on {phase.depends_on!r}, which is "
                        "not declared before it."
                    )
            if phase.scoring_window is not None and self.warmup_periods:
                raise ValueError(
                    f"phase {phase.name!r} declares a scoring_window while the "
                    "calibration declares warmup_periods; pick one convention."
                )
            for path in phase.overrides:
                if not path or path.startswith(".") or path.endswith("."):
                    raise ValueError(
                        f"phase {phase.name!r} overrides {path!r}, which is not a "
                        "dotted path into the configuration."
                    )
                if path.startswith("calibration."):
                    raise ValueError(
                        f"phase {phase.name!r} overrides {path!r}: a phase declares its "
                        "own search through its own fields, not by rewriting the "
                        "calibration section under itself."
                    )
                owner = frozen_by.get(path)
                if owner is not None:
                    raise ValueError(
                        f"phase {phase.name!r} overrides {path!r}, which phase {owner!r} "
                        "freezes; the calibrated value would be overwritten and nothing "
                        "downstream would say which one the model ran with."
                    )
            if phase.is_single_metric and (phase.outputs or phase.objective_blocks):
                raise ValueError(
                    f"phase {phase.name!r} declares a single-metric objective and also "
                    "selects outputs or objective blocks; the two are scored by "
                    "different routes and only one of them would run. Pick one "
                    "convention."
                )
        return self

    @model_validator(mode="after")
    def _refuse_two_burn_in_conventions(self) -> CalibrationConfig:
        """A window in dates and a count of samples must not both be declared.

        They say the same thing in two units, and the count means a different
        span at every output frequency, so honouring both would make the scored
        span depend on which one the reader noticed.
        """
        if self.scoring_window is not None and self.warmup_periods:
            raise ValueError(
                "declare either scoring_window (dates) or warmup_periods (samples), not both."
            )
        return self

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
    def _check_network_criterion_is_paired(self) -> CalibrationConfig:
        """A network output and a distance metric only make sense together.

        Runs after the implicit block is built, so the ``(objective, variable)``
        route counts as a declaration. An unpaired network output would fall
        through to the single-metric head route, which reads none of the
        network fields and still returns a plausible number.
        """
        network_outputs = {
            name for name, output in self.outputs.items() if output.support == "network"
        }
        distance_metrics = ("distance_gap", "distance_mean")
        scored: set[str] = set()
        for block in self.objective_blocks:
            if block.metric not in distance_metrics:
                continue
            without = sorted(set(block.uses_outputs) - network_outputs)
            if without:
                raise ValueError(
                    f"block {block.name!r} scores {block.metric!r} on {without}, which "
                    "is not a network output. That metric reads the pair (D_so, D_os) "
                    "only a network output produces."
                )
            scored.update(block.uses_outputs)
        unpaired = sorted(network_outputs - scored)
        if unpaired:
            raise ValueError(
                f"the network output(s) {unpaired} produce the pair (D_so, D_os), which "
                "only the metrics 'distance_gap' and 'distance_mean' can read; no block "
                "declares either on them. Left unscored they are silently ignored and "
                "the calibration falls back to its single metric."
            )
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
    "CalibOutputPoint",
    "CalibOutputBoundary",
    "CalibOutputCell",
    "CalibOutputLake",
    "CalibOutputNetwork",
    "CalibPhaseDecl",
    "CalibObjectiveBlockDecl",
    "SaveRunsMode",
    "ParameterMode",
    "OutputSupport",
    "OutputReducer",
    "OutputTime",
    "ObjectiveTransform",
    "PersistIterationDetail",
    "CalibrationMethod",
    "MetricKind",
    "validate_calib_output",
]
