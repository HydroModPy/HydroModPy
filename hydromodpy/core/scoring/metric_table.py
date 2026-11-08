"""The table of the sixteen metrics a score or a trial may be named after.

Calibration scores a trial on ten of them, a sealed run is scored on eleven, five
belong to both. Each name has one row here. The names a TOML may write, the
direction of a metric, its clipping and its documentation all come from these
rows, so a name is written once.

The kernels that compute a metric stay where they are: ``calibration.criteria``
pairs a name with its trial kernel and ``results.metric_rule`` with its run kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

MetricSense = Literal["max", "min", "zero", "one"]
"""Which value of a metric is the good one.

``max``: a higher value is better (efficiency scores). ``min``: a lower value is
better (errors, costs). ``zero``: the value closest to zero is better (signed
biases). ``one``: the value closest to one is better (KGE ratios).
"""


@dataclass(frozen=True)
class MetricSpec:
    """One metric: its name, its direction, its words and what it does to a series.

    ``trial_position`` and ``run_position`` are the place of the metric among the
    metrics a trial and a sealed run are scored on, counted from zero, and ``None``
    when that side does not use it. The two orders differ because they were written
    at different times and the files that read them keep that order.
    """

    name: str
    sense: MetricSense
    doc: str
    trial_position: int | None = None
    run_position: int | None = None
    clips_negatives: bool = False
    dimensionless: bool = False
    network: bool = False

    @property
    def scores_a_trial(self) -> bool:
        """Whether calibration can score a trial on this metric."""
        return self.trial_position is not None

    @property
    def scores_a_run(self) -> bool:
        """Whether a sealed run is scored on this metric."""
        return self.run_position is not None


_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "rmse",
        "min",
        "Root-mean-square error, in the observed unit; penalizes large misfits most.",
        trial_position=0,
        run_position=2,
    ),
    MetricSpec(
        "nse",
        "max",
        "Nash-Sutcliffe efficiency against the observed mean; the "
        "standard choice for a level or discharge series.",
        trial_position=1,
        run_position=0,
        dimensionless=True,
    ),
    MetricSpec(
        "kge",
        "max",
        "Kling-Gupta efficiency, 2009 form (bias as the ratio of sums, "
        "variability as the ratio of standard deviations); separates correlation, "
        "variability and bias when NSE alone is ambiguous.",
        trial_position=2,
        run_position=1,
        dimensionless=True,
    ),
    MetricSpec(
        "mae",
        "min",
        "Mean absolute error, in the observed unit; less sensitive to outliers than RMSE.",
        trial_position=3,
        run_position=4,
    ),
    MetricSpec(
        "nse_log",
        "max",
        "NSE on log-transformed series; weights low flows as "
        "heavily as peaks, good for recessions.",
        trial_position=4,
        run_position=3,
        clips_negatives=True,
        dimensionless=True,
    ),
    MetricSpec(
        "nse_delta",
        "max",
        "NSE on the increments of the series rather than its "
        "level; a level is an integral and can hide flux errors that "
        "compensate, which only its increments show.",
        trial_position=5,
        dimensionless=True,
    ),
    MetricSpec(
        "nse_seasonal",
        "max",
        "NSE against the seasonal cycle rather than the "
        "overall mean; asks whether the model beats climatology.",
        trial_position=6,
        dimensionless=True,
    ),
    MetricSpec(
        "reservoir",
        "max",
        "Half nse_seasonal plus half nse_delta, built for an "
        "impounded level: a plain NSE there is beaten by the seasonal cycle, "
        "and the increments are what carry the flux errors.",
        trial_position=7,
        dimensionless=True,
    ),
    MetricSpec(
        "distance_gap",
        "min",
        "Balances the simulated stream network against the mapped one; zero marks the crossing.",
        trial_position=8,
        network=True,
    ),
    MetricSpec(
        "distance_mean",
        "min",
        "Mean spatial offset between simulated and mapped "
        "streams; a diagnostic, not a substitute for distance_gap.",
        trial_position=9,
        network=True,
    ),
    MetricSpec(
        "bias",
        "zero",
        "Mean of simulated minus observed, in the observed unit.",
        run_position=5,
    ),
    MetricSpec(
        "pbias",
        "zero",
        "Sum of simulated minus observed, as a percentage of the observed sum.",
        run_position=6,
    ),
    MetricSpec(
        "correlation",
        "max",
        "Pearson correlation between simulated and observed values.",
        run_position=7,
    ),
    MetricSpec(
        "kge_r",
        "max",
        "Correlation term of the KGE: tells timing.",
        run_position=8,
    ),
    MetricSpec(
        "kge_alpha",
        "one",
        "Variability term of the KGE, the ratio of standard deviations: tells amplitude.",
        run_position=9,
    ),
    MetricSpec(
        "kge_beta",
        "one",
        "Bias term of the KGE, the ratio of sums: tells volume.",
        run_position=10,
    ),
)

METRIC_SPECS: Final[dict[str, MetricSpec]] = {spec.name: spec for spec in _SPECS}
"""Every metric, by name."""

TRIAL_METRIC_NAMES: Final[tuple[str, ...]] = tuple(
    spec.name
    for spec in sorted(
        (s for s in _SPECS if s.trial_position is not None), key=lambda s: s.trial_position or 0
    )
)
"""The metrics a trial may be scored on, in the order calibration lists them."""

RUN_METRIC_NAMES: Final[tuple[str, ...]] = tuple(
    spec.name
    for spec in sorted(
        (s for s in _SPECS if s.run_position is not None), key=lambda s: s.run_position or 0
    )
)
"""The metrics a sealed run is scored on: the four headline scores, then the panel of a run.

The ``kge_*`` entries are the decomposition of the KGE, 2009 form (``beta`` is the
ratio of the sums, ``alpha`` the ratio of the standard deviations).
"""

NETWORK_METRIC_NAMES: Final[tuple[str, ...]] = tuple(s.name for s in _SPECS if s.network)
"""The metrics that score a stream network, not a series."""

METRIC_SENSE: Final[dict[str, MetricSense]] = {s.name: s.sense for s in _SPECS}
"""Direction of every metric the catalog knows how to rank."""

__all__ = [
    "METRIC_SENSE",
    "METRIC_SPECS",
    "NETWORK_METRIC_NAMES",
    "RUN_METRIC_NAMES",
    "TRIAL_METRIC_NAMES",
    "MetricSense",
    "MetricSpec",
]
