"""The protocol, parameter and objective blocks of a calibration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, ClassVar, Literal, TypeAlias

from pydantic import (
    Field,
    model_validator,
)

from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.config_terms import (
    METRIC_VALUE_DOCS,
    MetricKind,
    ObjectiveTransform,
    ParameterMode,
    renamed,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import PositiveFloat
from hydromodpy.core.scoring.metric_table import METRIC_SENSE

CalibrationProtocolDecl: TypeAlias = MatchingHydrographicNetworkOptions
"""What ``[calibration].protocol`` validates against.

One registered protocol today, so the alias names it directly. A second one
turns this into a union discriminated on ``name``; the registry and this alias
are kept in step by
``tests/unit/calibration/test_runners_phase_regime.py``.
"""


class CalibParameterDecl(HydroModelBase):
    """User declaration for one calibrated parameter.

    The declaration is read from ``[calibration.parameters.<name>]``, and the
    section name is the quantity: it is resolved against the catalog the
    project exposes, so a file states the range and nothing else. Writing
    ``path`` is the way out for whatever the catalog does not reach, and it
    wins without a lookup.

    Use ``mode="replace"`` for direct parameter values and ``mode="scale"``
    for multiplicative factors applied to an existing config value.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **renamed(
            {
                "transform": ("search_space", "the space the search walks the parameter in"),
                "prior": ("sampling", "the law that starting points and random draws follow"),
            }
        ),
    }

    bounds: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="[low, high] physical bounds, in 'units' when the file writes it, "
        "else in the unit the target declares. "
        "Falls back to what the field annotates when the file omits it, which most "
        "fields deliberately leave unset because a range belongs to the site.",
    )
    search_space: Annotated[Literal["identity", "log", "logit"], Profile.USER] = Field(
        default="identity",
        json_schema_extra=field_metadata(
            renamed_from=["calibration.parameters.transform"],
            value_docs={
                "identity": "Searches the value as written.",
                "log": (
                    "Searches the logarithm of the value: for a positive quantity that "
                    "spans orders of magnitude."
                ),
                "logit": (
                    "Searches log(x / (1 - x)): for a share strictly between 0 and 1. "
                    "Both bounds must lie inside (0, 1)."
                ),
            },
        ),
        description="Space the search walks the parameter in. 'log' for "
        "strictly-positive quantities spanning orders of magnitude. Unset, the "
        "target's own field decides: a hydraulic conductivity declares 'log' where "
        "it is defined, so a file states this only to depart from it.",
    )
    sampling: Annotated[Literal["uniform", "log_uniform", "normal"], Profile.USER] = Field(
        default="uniform",
        description=(
            "Distribution, between the bounds, that starting points, random draws and "
            "Bayesian samplers take values from."
        ),
        json_schema_extra=field_metadata(
            renamed_from=["calibration.parameters.prior"],
            value_docs={
                "uniform": "Every value between the bounds is equally likely.",
                "log_uniform": "Every decade between the bounds is equally likely.",
                "normal": (
                    "A normal law centred between the bounds, with a standard deviation "
                    "of a sixth of their span, cut at the bounds."
                ),
            },
        ),
    )
    path: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Dotted TOML path of the value to move, such as "
        "'flow.param.K.field.value'. Optional, and the way out "
        "rather than the way in: when omitted, the section name is resolved against "
        "the project catalogue ('hmp config targets' lists it). Write one to reach a "
        "value the catalogue does not carry, or to settle a name two targets answer "
        "to. A path written here wins without a lookup. When the catalogue carries it, "
        "the parameter inherits the field's space and draw like a named one; when it "
        "does not, nothing is inherited and the sample is written as it is drawn.",
    )
    target: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Readable alias for 'path'. Setting both is refused.",
    )
    mode: Annotated[ParameterMode, Profile.USER] = Field(
        default="replace",
        description="'replace' writes the sampled value as-is; 'scale' multiplies "
        "the base TOML value at the target path by the sample.",
    )
    units: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Unit the bounds are written in, such as 'm/s'. For a parameter the catalogue "
            "resolves, bounds in another unit of the same quantity are converted when the "
            "file loads into the unit the target is read in, and the search draws, writes "
            "and reports its samples in that unit ('hmp config targets' lists it). A unit "
            "of another quantity is refused. Unset, the unit of the target applies. With "
            "mode = 'scale' the bounds are factors without a unit, and writing one is "
            "refused. For a path outside the catalogue it is the unit the bounds are "
            "checked against the physical range in."
        ),
        examples=["m/s"],
    )

    @model_validator(mode="after")
    def _check_one_address(self) -> CalibParameterDecl:
        if self.path is not None and self.target is not None:
            raise ValueError(
                f"a parameter writes both path={self.path!r} and target={self.target!r}, "
                "two names for one address. Keep one of them."
            )
        return self

    def resolve_target(self) -> str | None:
        """Return ``target`` when set, else ``path`` (read-only helper)."""
        return self.target if self.target is not None else self.path


class CalibObjectiveBlockDecl(HydroModelBase):
    """Weighted metric block used by a composite objective.

    A block consumes one or more named outputs, applies one metric, and
    contributes ``weight`` to the final minimization cost. Blocks make mixed
    objectives explicit, for example combining heads, discharge, and transport
    signals in one calibration session.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **renamed(
            {
                "transform": (
                    "cost_transform",
                    "the function applied to the cost of this block",
                ),
            }
        ),
        "warmup": (
            "a window bounds every block: write window = {start = <date>} on [calibration] instead"
        ),
    }

    name: Annotated[str, Profile.USER] = Field(
        description="Unique block identifier used in logs and persistence.",
    )
    metric: Annotated[MetricKind, Profile.USER] = Field(
        description="Metric that scores this block against its observations.",
        json_schema_extra={"value_docs": METRIC_VALUE_DOCS},
    )
    weight: Annotated[PositiveFloat, Profile.USER] = Field(
        default=1.0,
        description=(
            "Weight of this block in the sum of the block costs. Only the ratios between "
            "weights matter."
        ),
        json_schema_extra={"unit": "-"},
    )
    uses_outputs: Annotated[list[str], Profile.USER] = Field(
        min_length=1,
        description=(
            "Outputs (by name) consumed by this block. An error metric (rmse, mae) or a "
            "network distance may read several, pooled into one cost. A metric that rises "
            "with the fit (nse, kge and the other efficiencies) reads exactly one: write "
            "one block per output, each with its weight, so the costs average per station."
        ),
    )
    normalize_cost: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="When True, divide the block cost by a reference scale, so it adds "
        "to other blocks as a pure number and a share means a share. On a residual "
        "metric (rmse, mae) the scale is the standard deviation of the observations, "
        "their mean absolute value if that is zero. On a network distance "
        "(distance_gap, distance_mean) it is the output's validity_length, 2 h_obs "
        "under 'auto': a gap of one validity length costs 1, as much as an NSE of 0 on "
        "nse_log. Refused on an efficiency score, already a pure number.",
    )
    cost_transform: Annotated[ObjectiveTransform, Profile.USER] = Field(
        default="identity",
        description="Transform applied to the cost of this block before weighting. Note "
        "that cost_transform='log' takes the logarithm of the cost, which is not the same "
        "thing as metric='nse_log', an NSE computed on log-transformed series.",
        json_schema_extra=field_metadata(
            renamed_from=["calibration.objective_blocks.transform"],
            value_docs={
                "identity": "Uses the block cost as computed, with no transform.",
                "log": "Takes log10 of the cost plus a small epsilon, compressing "
                "large costs before weighting.",
                "inverse": "Takes -1 / (cost + epsilon), sharpening the gradient near "
                "a cost of zero.",
            },
        ),
    )

    @model_validator(mode="after")
    def _check_an_efficiency_reads_one_output(self) -> CalibObjectiveBlockDecl:
        """Refuse an efficiency over several outputs.

        The pool of several stations has the spread between them as variance, so
        one badly simulated station hides behind it. One block per output
        averages the costs per station instead.
        """
        metric = str(self.metric).lower()
        if METRIC_SENSE.get(metric) == "max" and len(self.uses_outputs) > 1:
            listed = ", ".join(repr(name) for name in self.uses_outputs)
            raise ValueError(
                f"block {self.name!r} scores {metric!r} on {len(self.uses_outputs)} outputs "
                f"({listed}). An efficiency computed on the pool of several outputs is not "
                "the mean of their efficiencies, and a poorly simulated station hides "
                "behind the spread between stations. Write one block per output, each "
                "with its weight, so the costs average per station."
            )
        return self

    @model_validator(mode="after")
    def _check_the_normalisation_means_something(self) -> CalibObjectiveBlockDecl:
        """Refuse here what the objective would refuse at the first trial.

        The reader of this message writes TOML, so the refusal belongs where the
        file is read rather than hours later inside a search.
        """
        if self.normalize_cost:
            from hydromodpy.calibration.optim.objective import (
                refuse_a_normalisation_that_means_nothing,
            )

            refuse_a_normalisation_that_means_nothing(self.name, str(self.metric).lower())
        return self
