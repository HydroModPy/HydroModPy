"""The table of metrics gives every name list the code reads, in the order they had before.

The lists written below were read off the tree before the table existed. A name
added to the table moves them, and then this file is where the move is written.
"""

from __future__ import annotations

from typing import get_args

import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    MatchingHydrographicNetworkOptions,
    MetricKind,
)
from hydromodpy.calibration.criteria.formulas import METRIC_FORMULAS
from hydromodpy.calibration.criteria.hydrographic_network_distance import Estimator
from hydromodpy.calibration.criteria.series import METRICS
from hydromodpy.core.scoring.metric_table import (
    METRIC_SENSE,
    METRIC_SPECS,
    NETWORK_METRIC_NAMES,
    RUN_METRIC_NAMES,
    TRIAL_METRIC_NAMES,
)
from hydromodpy.results.metric_rule import _KERNELS, HEADLINE_METRICS

pytestmark = pytest.mark.unit

TRIAL_BEFORE = (
    "rmse",
    "nse",
    "kge",
    "mae",
    "nse_log",
    "nse_delta",
    "nse_seasonal",
    "reservoir",
    "distance_gap",
    "distance_mean",
)
RUN_BEFORE = (
    "nse",
    "kge",
    "rmse",
    "nse_log",
    "mae",
    "bias",
    "pbias",
    "correlation",
    "kge_r",
    "kge_alpha",
    "kge_beta",
)
SENSE_BEFORE = {
    "nse": "max",
    "nse_log": "max",
    "nse_delta": "max",
    "nse_seasonal": "max",
    "kge": "max",
    "kge_r": "max",
    "correlation": "max",
    "reservoir": "max",
    "rmse": "min",
    "mae": "min",
    "distance_gap": "min",
    "distance_mean": "min",
    "bias": "zero",
    "pbias": "zero",
    "kge_alpha": "one",
    "kge_beta": "one",
}


@pytest.mark.parametrize(
    ("derived", "before"),
    [
        (TRIAL_METRIC_NAMES, TRIAL_BEFORE),
        (RUN_METRIC_NAMES, RUN_BEFORE),
        (NETWORK_METRIC_NAMES, ("distance_gap", "distance_mean")),
        (tuple(get_args(MetricKind)), TRIAL_BEFORE),
        (tuple(get_args(Estimator)), ("distance_gap", "distance_mean")),
    ],
    ids=["trial", "run", "network", "MetricKind", "Estimator"],
)
def test_a_name_list_derived_from_the_table_is_the_one_it_replaced(
    derived: tuple[str, ...], before: tuple[str, ...]
) -> None:
    assert derived == before


def test_the_table_holds_sixteen_names_once() -> None:
    assert len(METRIC_SPECS) == 16
    assert all(name == spec.name for name, spec in METRIC_SPECS.items())
    assert set(METRIC_SPECS) == set(TRIAL_BEFORE) | set(RUN_BEFORE)


def test_ten_names_score_a_trial_eleven_a_run_and_five_both() -> None:
    both = set(TRIAL_METRIC_NAMES) & set(RUN_METRIC_NAMES)
    assert (len(TRIAL_METRIC_NAMES), len(RUN_METRIC_NAMES), len(both)) == (10, 11, 5)
    assert all(METRIC_SPECS[name].scores_a_trial for name in TRIAL_METRIC_NAMES)
    assert all(METRIC_SPECS[name].scores_a_run for name in RUN_METRIC_NAMES)


@pytest.mark.parametrize("name", sorted(METRIC_SPECS))
def test_every_name_has_the_direction_it_had(name: str) -> None:
    assert METRIC_SENSE[name] == SENSE_BEFORE[name]


def test_the_positions_of_a_side_are_a_run_of_integers_from_zero() -> None:
    for side in ("trial_position", "run_position"):
        positions = sorted(
            getattr(s, side) for s in METRIC_SPECS.values() if getattr(s, side) is not None
        )
        assert positions == list(range(len(positions)))


def test_the_flags_mark_the_names_the_hand_written_sets_held() -> None:
    clipping = {n for n, s in METRIC_SPECS.items() if s.clips_negatives}
    dimensionless = {n for n, s in METRIC_SPECS.items() if s.dimensionless}
    assert clipping == {"nse_log"}
    assert dimensionless == {"nse", "kge", "nse_delta", "nse_seasonal", "nse_log", "reservoir"}
    assert dimensionless <= set(TRIAL_METRIC_NAMES)


def test_the_trial_kernels_are_the_trial_names() -> None:
    assert set(METRICS) == set(TRIAL_METRIC_NAMES)


def test_the_run_kernels_are_the_run_names_in_order() -> None:
    assert tuple(_KERNELS) == RUN_METRIC_NAMES


def test_the_headline_scores_and_the_formulas_are_names_of_the_table() -> None:
    assert set(HEADLINE_METRICS) <= set(RUN_METRIC_NAMES)
    assert set(METRIC_FORMULAS) <= set(METRIC_SPECS)


def test_every_trial_name_has_a_sentence_in_the_field_documentation() -> None:
    extra = CalibObjectiveBlockDecl.model_fields["metric"].json_schema_extra
    assert isinstance(extra, dict)
    assert extra["value_docs"] == {n: METRIC_SPECS[n].doc for n in TRIAL_METRIC_NAMES}
    assert all(spec.doc for spec in METRIC_SPECS.values())


def test_the_steady_metric_of_the_network_stage_offers_the_network_names() -> None:
    annotation = MatchingHydrographicNetworkOptions.model_fields["steady_metric"].annotation
    assert get_args(annotation) == NETWORK_METRIC_NAMES
