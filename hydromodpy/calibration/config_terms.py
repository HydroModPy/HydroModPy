"""The words a calibration TOML uses: value aliases, windows, renamed keys."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.core.scoring.metric_table import (
    METRIC_SPECS,
    TRIAL_METRIC_NAMES,
)
from hydromodpy.schema.changes import prerelease_refusal


def renamed_to(old: str, new: str, meaning: str) -> str:
    """Return the refusal of a key that a pre-release of 2.0 wrote under its old name.

    It is a value of ``model_refused_keys``. *meaning* says in one clause what the new
    key is, so a reader who never saw the old name still learns what to write. The
    sentence of :func:`hydromodpy.schema.changes.prerelease_refusal` follows.
    """
    return f"renamed to {new!r} ({meaning}). {prerelease_refusal(THIS_TABLE, [old])}"


def renamed(renames: Mapping[str, tuple[str, str]]) -> dict[str, str]:
    """Return the refusals of keys given as old key: (new key, what it is)."""
    return {old: renamed_to(old, new, meaning) for old, (new, meaning) in renames.items()}


def never_read(*keys: str) -> dict[str, str]:
    """Return the refusals of keys that a pre-release declared and no step ever read.

    No run depended on such a key, so the file loses nothing when the key goes.
    """
    return {key: "no step ever read it, so delete it from the file." for key in keys}


THIS_TABLE = "This table"


GAUGE_ADVICE = (
    "the station is [site] gauge, and a point output names its own with 'observes'. "
    + prerelease_refusal(THIS_TABLE, ["observed_station_id"])
)


SaveRunsMode = Literal["none", "best_n", "all"]


ParameterMode = Literal["replace", "scale"]


OutputSupport = Literal["point", "boundary", "cell", "lake", "network"]


OutputReducer = Literal["mean", "sum", "last", "none"]


OUTPUT_REDUCER_VALUE_DOCS: dict[str, str] = {
    "mean": "Scores one value: the mean of the kept values.",
    "sum": "Scores one value: the sum of the kept values.",
    "last": "Scores one value: the last kept value.",
    "none": "Scores every kept value against its observation.",
}
"""What each reducer of a calibration output does to the kept time steps."""


ObjectiveTransform = Literal["identity", "log", "inverse"]


PersistIterationDetail = Literal["none", "summary", "full"]


MetricKind = Literal[*TRIAL_METRIC_NAMES]
"""Metric names a TOML may select: the trial metrics of ``core.scoring.metric_table``."""


METRIC_VALUE_DOCS: dict[str, str] = {name: METRIC_SPECS[name].doc for name in TRIAL_METRIC_NAMES}
"""What each metric a TOML may select measures, shown beside every key that picks one."""


def validated_method_for(key: str) -> Callable[[str], str]:
    def _validate(value: str) -> str:
        from hydromodpy.calibration.optim.optimizer import ENTRY_POINT_GROUP, optimizers

        return check_registered_name(
            value,
            names=optimizers.names(),
            key=key,
            group=ENTRY_POINT_GROUP,
        )

    return _validate


CalibrationMethod = Annotated[
    str,
    AfterValidator(validated_method_for("calibration.method")),
]
"""A calibration method name, one of the optimizers this installation serves.

Validated once, when the file is read, so a typo fails beside the field that wrote
it and not in the depths of an adapter. The shared registry is the single source:
``optimizers.names()`` and the refusal sentence are the ones
:func:`hydromodpy.core.plugin_registry.check_registered_name` prints, and
``da_mh_gp`` is one of the names served.
"""


def _no_list_of_dates(value: Any) -> Any:
    """Refuse a list of dates as the time of a series output: nothing selects them."""
    if isinstance(value, list):
        raise ValueError(
            "time = [dates] selects nothing: the output would be read at every step, as "
            "with 'all'. Bound what is scored with [metrics] window or window, or "
            "write 'first' or 'last'."
        )
    return value


OutputTime = Annotated[Literal["all", "last", "first"], BeforeValidator(_no_list_of_dates)]


class CalibWindow(HydroModelBase):
    """Dates bounding the samples a metric is computed on.

    A window in dates rather than in sample counts: it says the same thing
    whatever the output frequency.
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
    def _check_bounds(self) -> CalibWindow:
        bounds = _parsed_bounds(self)
        if bounds[0] is not None and bounds[1] is not None and bounds[0] > bounds[1]:
            raise ValueError(f"window start {self.start!r} is after end {self.end!r}.")
        return self


def _parsed_bounds(window: CalibWindow) -> tuple[Any, Any]:
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
            raise ValueError(f"window {label}={raw!r} is not a date.") from exc
    return parsed[0], parsed[1]


def window_bounds(window: CalibWindow | None) -> tuple[Any, Any] | None:
    """Return the parsed ``(start, end)`` of a window, or None when unset."""
    if window is None:
        return None
    return _parsed_bounds(window)


def _a_steady_span(window: dict[str, str]) -> dict[str, str]:
    """Read a steady span, a window that needs both of its bounds."""
    missing = [key for key in ("start", "end") if not window.get(key)]
    if missing:
        raise ValueError(
            f"steady_window needs both 'start' and 'end'; missing {', '.join(missing)}."
        )
    CalibWindow.model_validate(window)
    return dict(window)


ProtocolSteadySpan: TypeAlias = Annotated[
    dict[Literal["start", "end"], str], AfterValidator(_a_steady_span)
]
"""A ``{start, end}`` table of ISO dates, both bounds required."""


def moved_from(*keys: str, **metadata: Any) -> dict[str, Any]:
    """Return the metadata of a network field that holds these old keys of its output."""
    return field_metadata(renamed_from=[f"calibration.outputs.{key}" for key in keys], **metadata)


_OPTIONS_WITHOUT_A_METHOD = (
    "{where} gives method_options and no method. They are options of one method, "
    "and a search that names no method gets the one its criteria call for. Write "
    "method beside them or under [calibration], or drop them."
)


def check_the_method_takes_its_options(
    where: str, method: str | None, options: Mapping[str, Any], *, key: str = "method_options"
) -> None:
    """Refuse options with no method, and options the method written does not take.

    Checked when the file loads, so a phase-two option its method does not know
    is refused before phase one spends its budget. A method this package has no
    model for, a plugin's, is left to its own constructor.
    """
    if not options:
        return
    if method is None:
        raise ValueError(_OPTIONS_WITHOUT_A_METHOD.format(where=where))
    from hydromodpy.calibration.optim.method_config import method_options_problem

    problem = method_options_problem(method, options)
    if problem is not None:
        raise ValueError(f"{where} {key}: {problem}")
